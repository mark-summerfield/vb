#!/usr/bin/env python3
# Copyright © 2020-2 Mark Summerfield. All rights reserved.
# License: GPLv3

import contextlib
import datetime
import enum
import getpass
import glob
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile

__version__ = '1.0.0'


def main():
    model = Model()
    ini = model.maybe_read_master_ini()
    try:
        action = model.read_args()
        if action in {Action.CLEAN, Action.NEW, Action.BUILD}:
            if model.verbose and ini is not None:
                print(f'read:     {ini}')
        if action is Action.CLEAN:
            model.clean()
        elif action is Action.USAGE:
            print(USAGE)
        elif action is Action.INI_USAGE:
            print(INI_USAGE)
        elif action is Action.VERSION:
            print(__version__)
        elif action is Action.NEW:
            model.new()
        else: # action is Action.BUILD
            model.discover()
            model.build()
            if WIN and model.archive:
                model.win_zip()
            if model.run:
                model.run_exe()
    except Error as err:
        print(f'error:   {err}')


class Model:

    def __init__(self, verbose=True, run=True, console=False,
                 archive=False):
        self.appname = None
        self.verbose = verbose
        self.run = run
        self.console = console
        self.archive = archive
        self.packages = {}
        self.valas = None
        self.root = None
        self.args = []
        self.version = None
        self.extra_files = ['README', 'LICENSE']
        self.winrcedit = 'C:/bin/rcedit.exe'
        self.winmsys2 = 'C:/bin/msys64'
        self.app_template = APP_TEMPLATE
        self.gui_template = GUI_TEMPLATE
        self.lib_template = LIB_TEMPLATE


    def maybe_read_master_ini(self):
        ini = pathlib.Path.home() / f'.config/{GLOBAL_INI}'
        if not ini.exists():
            ini = pathlib.Path.home() / f'.{GLOBAL_INI}'
            if not ini.exists():
                ini = pathlib.Path.home() / GLOBAL_INI
        if ini.exists():
            self.read_ini(ini, master=True)
            return ini
        # else return None


    def read_args(self):
        action = Action.BUILD
        for arg in sys.argv[1:]:
            if arg in {'-v', '--version', 'version'}:
                action = Action.VERSION
                break
            if arg in {'-c', '--clean', 'clean'}:
                action = Action.CLEAN
                break
            if arg in {'-h', '--help', 'help'}:
                action = Action.USAGE
            elif arg in {'-n', '--new', 'new', 'init'}:
                action = Action.NEW
            elif arg in {'-q', '--quiet', 'quiet'}:
                self.verbose = False
            elif arg in {'-b', '--build', 'build'}:
                self.run = False
            elif arg in {'-C', '--console', 'console'}:
                self.console = True
            elif arg in {'-z', '--zip', 'zip'}:
                self.archive = True
            elif action == Action.USAGE:
                if arg.upper() == 'INI':
                    action = Action.INI_USAGE
                break
            else:
                self.args.append(arg)
        return action


    def clean(self):
        self.get_appname()
        appname = self.appname
        if WIN:
            appname += '.exe'
            dist = pathlib.Path('./dist')
            if self.verbose:
                print(f'delete:  {dist}')
            with contextlib.suppress(FileNotFoundError):
                shutil.rmtree(dist)
        if self.verbose:
            print(f'delete:  {appname}')
        with contextlib.suppress(FileNotFoundError):
            pathlib.Path(appname).unlink()


    def get_appname(self):
        self.root = pathlib.Path('.')
        ini = self.root / LOCAL_INI
        if ini.exists():
            self.read_ini(ini, master=False)
        self.valas = [vala for vala in self.root.glob('*.vala')]
        if not self.valas:
            raise Error('no .vala files found')
        if not self.appname:
            if len(self.valas) == 1:
                self.appname = self.valas[0].stem
            else:
                self.appname = self.root.name


    def read_ini(self, ini, *, master):
        category = Category.GENERAL
        with open(ini, 'rt', encoding='utf-8') as file:
            for line in file:
                if not line.startswith('[') and category in {
                        Category.APP_TEMPLATE, Category.GUI_TEMPLATE,
                        Category.LIB_TEMPLATE}:
                    self.add_template_line(category, line)
                    continue
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('['):
                    category = self.read_ini_category(category, line)
                else:
                    self.read_ini_item(category, line, master)
        if self.verbose and not master:
            print(f'read:     {ini}')


    def read_ini_category(self, category, line):
        i = line.find(']')
        if i > -1:
            category = line[1:i].casefold()
            if category == 'packages':
                category = Category.PACKAGES
            elif category == 'extrafiles':
                self.extra_files = []
                category = Category.EXTRA_FILES
            elif category == 'apptemplate':
                category = Category.APP_TEMPLATE
                self.app_template = ''
            elif category == 'guitemplate':
                category = Category.GUI_TEMPLATE
                self.gui_template = ''
            elif category == 'libtemplate':
                category = Category.LIB_TEMPLATE
                self.lib_template = ''
            else:
                category = Category.GENERAL
        return category


    def read_ini_item(self, category, line, master):
        if category in {Category.APP_TEMPLATE, Category.GUI_TEMPLATE,
                        Category.LIB_TEMPLATE}:
            self.add_template_line(category, line)
        elif category is Category.EXTRA_FILES:
            self.extra_files += glob.glob(line)
        else:
            parts = line.split('=', 2)
            if len(parts) == 2:
                key = parts[0].strip().casefold()
                value = parts[1].strip()
                if category is Category.PACKAGES:
                    key = key.title()
                    if master:
                        Packages[key] = value
                    else:
                        self.packages[key] = value
                        Packages.pop(key)
                else: # category is Category.GENERAL
                    self.set_general_item(key, value)


    def add_template_line(self, category, line):
        if category is Category.APP_TEMPLATE:
            self.app_template += line
        elif category is Category.GUI_TEMPLATE:
            self.gui_template += line
        elif category is Category.LIB_TEMPLATE:
            self.lib_template += line


    def set_general_item(self, key, value):
        if key == 'appname': # Not recommended; see USAGE
            self.appname = value
        elif key == 'version': # Not recommended; see USAGE
            self.version = value
        elif key == 'winrcedit':
            self.winrcedit = value
        elif key == 'winmsys2':
            self.winmsys2 = value


    def discover(self):
        tick = time.monotonic()
        self.get_appname()
        more_to_do = lambda: Packages or (WIN and self.archive and
                                          self.version is None)
        if more_to_do():
            pkg_rx = re.compile(START + '|'.join(Packages.keys()) + END)
            for vala in self.valas:
                with open(vala, 'rt', encoding='utf-8') as file:
                    for line in file:
                        if not more_to_do():
                            break
                        match = pkg_rx.search(line)
                        if match is not None:
                            pkg_rx = self.update_packages(
                                pkg_rx, match.group('pkg'))
                            continue
                        if GIO in Packages:
                            match = GIO_RX.search(line)
                            if match is not None:
                                pkg_rx = self.update_packages(pkg_rx, GIO)
                                continue
                        if self.version is None:
                            match = VERSION_RX.search(line)
                            if match is not None:
                                self.version = match.group('version')
                if not more_to_do():
                    break
        ini = self.root / LOCAL_INI
        if ini.exists():
            self.maybe_update_ini(ini)
        else:
            self.make_ini(ini)
        tick = time.monotonic() - tick
        if self.verbose and tick > 0.1:
            print(f'discover: {tick:0.3f} sec')


    def update_packages(self, pkg_rx, pkg):
        self.packages[pkg] = Packages[pkg]
        del Packages[pkg]
        if Packages:
            return re.compile(START + '|'.join(Packages.keys()) + END)
        return pkg_rx


    def make_ini(self, ini):
        with open(ini, 'wt', encoding='utf-8') as file:
            file.write('[General]\n')
            file.write('\n[ExtraFiles]\n\n')
            file.write(self.make_packages_section(self.packages))
        if self.verbose:
            print(f'wrote:    {ini.relative_to(self.root)}')


    def make_packages_section(self, packages):
        section = '[Packages]\n'
        lines = set()
        for name, value in packages.items():
            lines.add(f'{name} = {value}')
        for name, value in Packages.items():
            lines.add(f'# {name} = {value}')
        return section + '\n'.join(sorted(lines)) + '\n'


    def maybe_update_ini(self, ini):
        with open(ini, 'rt', encoding='utf-8') as file:
            old = file.readlines()
        new = []
        in_packages = False
        packages = self.packages.copy()
        for line in old:
            if in_packages:
                parts = line.split('=', 2)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    if key.startswith('#'):
                        keyx = key
                        key = key.lstrip('# ')
                        if key not in packages:
                            packages[keyx] = value
                            continue
                    packages[key] = value
            elif not line.upper().startswith('[PACKAGES]'):
                new.append(line)
            else:
                in_packages = True
        old = ''.join(old)
        new = ''.join(new) + self.make_packages_section(packages)
        if new != old:
            with open(ini, 'wt', encoding='utf-8') as file:
                file.write(new)
            print(f'update:   {ini.relative_to(self.root)}')


    def build(self):
        args = ['valac', '-o', self.appname]
        if WIN and not self.console and 'Gtk' in self.packages:
            args += ['-X', '-mwindows']
        for pkg in self.packages.values():
            args += ['--pkg', pkg]
        args += [str(vala) for vala in self.valas]
        if self.verbose:
            print('build:   ', ' '.join(args))
        if subprocess.run(args).returncode != 0:
            raise Error('failed to build')
        if WIN:
            self.make_win_dist()
        else:
            self.appname = self.root / self.appname


    def make_win_dist(self):
        self.appname += '.exe'
        self.maybe_add_win_icon()
        dist = self.root / 'dist'
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(dist)
        dist.mkdir()
        self.maybe_copy_extra_win_files(dist)
        reply = subprocess.run(['ldd', self.appname], capture_output=True)
        if reply.returncode != 0:
            raise Error('failed to run ldd to determine DLL dependencies')
        shutil.move(self.appname, dist) # must be after ldd
        if self.verbose:
            print(f'move:     {self.appname} to {dist}')
        self.maybe_copy_win_dlls(dist, reply.stdout.decode('utf-8'))
        self.appname = dist / self.appname


    def maybe_add_win_icon(self):
        icon = self.root / 'icon.ico'
        if not icon.exists():
            icon = self.root / 'images/icon.ico'
        if icon.exists():
            try:
                args = [self.winrcedit, self.appname, '--set-icon',
                        str(icon)]
                if subprocess.run(args).returncode != 0:
                    print(f'warning:  failed to add icon to {self.appname}')
                elif self.verbose:
                    print(f'add:      {icon}')
            except FileNotFoundError:
                if self.verbose:
                    print('warning:  failed to find rcedit.exe so no icon '
                          f'added to {self.appname}')


    def maybe_copy_extra_win_files(self, dist):
        extras = 0
        for filename in self.extra_files:
            extras += self.copy_optional_win_file(dist, filename)
        if self.verbose and extras:
            s = '' if extras == 1 else 's'
            print(f'copy:     {extras:,} extra file{s} to {dist}')


    def copy_optional_win_file(self, dist, filename):
        name = pathlib.Path(filename)
        if not name.exists() and str(name).upper().startswith(('README',
                                                               'LICENSE')):
            name = name.with_suffix('.txt')
            if not name.exists():
                name = name.with_suffix('.md')
        if name.exists():
            if str(name.parent) != '.':
                dist = dist / name.parent
                dist.mkdir(parents=True, exist_ok=True)
            shutil.copy2(name, dist)
            return 1
        return 0


    def maybe_copy_win_dlls(self, dist, dlls):
        dll_rx = re.compile(r'^\s*\S+\s=>\s(?P<dll>\S+)')
        dll_count = 0
        for line in dlls.splitlines():
            match = dll_rx.match(line)
            if match is not None:
                dll = match.group('dll')
                if 'mingw64' in dll:
                    dll = self.winmsys2 + dll
                    shutil.copy2(dll, dist)
                    dll_count += 1
        if self.verbose and dll_count:
            print(f'copy:     {dll_count:,} DLLs to {dist}')


    def run_exe(self):
        if WIN:
            args = [str(self.appname)]
        else:
            args = [f'./{self.appname}']
        args += self.args
        if self.verbose:
            print('run:     ', ' '.join(args))
        if subprocess.run(args).returncode != 0:
            print(f'warning:  failed to run {self.appname}')


    def win_zip(self):
        dist = self.root / 'dist'
        target = pathlib.Path(self.appname).with_suffix('')
        name = target.name
        if self.version:
            name = f'{target.name}-{self.version}'
            target = target.with_name(name)
        target = target.with_suffix('.zip')
        with zipfile.ZipFile(target, 'w',
                             compression=zipfile.ZIP_DEFLATED) as file:
            for filename in dist.glob('**/*'):
                if not target.samefile(filename):
                    file.write(filename,
                               f'{name}/{str(filename.relative_to(dist))}')
        if self.verbose:
            print(f'create:   {target}')


    def new(self):
        kind = self.prepare_new()
        path = pathlib.Path(self.appname)
        if path.exists():
            raise Error(
                f'a file/directory called {self.appname} already exists')
        if kind is New.LIB:
            raise Error("creating libraries isn't supported yet")
        path.mkdir()
        os.chdir(path)
        self.make_gitignore()
        self.make_vala(kind)
        self.make_st_sh()
        self.make_new_ini(kind)
        self.make_manifest()
        self.make_readme()
        shutil.copyfile('/usr/share/common-licenses/GPL-3', 'LICENSE')
        self.initialise_vcs()
        if self.verbose:
            print(f'new:      {self.appname}')


    def prepare_new(self):
        kinds = New.names()
        if len(self.args) not in {1, 2}:
            kinds = '|'.join(kinds).lower()
            raise Error(f'new needs one or two arguments: [{kinds}] <NAME>')
        if len(self.args) == 2:
            kind = self.args.pop(0).upper()
            if kind not in kinds:
                kinds = '|'.join(kinds).lower()
                raise Error(f"new's kind must be one of [{kinds}]")
            kind = New.from_name(kind)
        else:
            kind = New.APP
        name = self.args.pop(0)
        if name.upper() in kinds:
            raise Error("new's kind must be followed by a NAME")
        self.appname = name
        return kind


    def make_gitignore(self):
        gitignore = '.gitignore'
        try:
            shutil.copy(pathlib.Path(f'~/{gitignore}').expanduser(),
                        gitignore)
        except FileNotFoundError:
            print('warning:  failed to copy and edit .gitignore')
            return
        with open(gitignore, 'rt', encoding='utf-8') as file:
            text = file.read()
        with open(gitignore, 'wt', encoding='utf-8') as file:
            file.write(text)
            file.write(f'{self.appname}\n{self.appname}.exe\ndist/\n')


    def make_vala(self, kind):
        template = (self.app_template if kind is New.APP else
                    self.gui_template)
        template = (template
                    .replace('#YEAR#', str(datetime.date.today().year))
                    .replace('#APPNAME#', self.appname)
                    .replace('#USER#', getpass.getuser()))
        vala = f'{self.appname}.vala'
        with open(vala, 'wt', encoding='utf-8') as file:
            file.write(template)


    def make_st_sh(self):
        st_sh = 'st.sh'
        with open(st_sh, 'wt', encoding='utf-8') as file:
            file.write('#!/bin/bash\ntokei -f -c80 -tVala\ngit st\n')
        st = os.stat(st_sh)
        os.chmod(st_sh, st.st_mode | stat.S_IEXEC)


    def make_new_ini(self, kind):
        with open(LOCAL_INI, 'wt', encoding='utf-8') as file:
            file.write('[General]\n')
            file.write('\n[ExtraFiles]\n')
            file.write('\n[Packages]\n')
            for name, value in Packages.items():
                prefix = '' if kind is New.GUI and name == 'Gtk' else '# '
                file.write(f'{prefix}{name} = {value}\n')


    def make_manifest(self):
        with open('MANIFEST', 'wt', encoding='utf-8') as file:
            file.write(f'{self.appname}.vala\n\n{LOCAL_INI}\n\nst.sh\n')


    def make_readme(self):
        with open('README.md', 'wt', encoding='utf-8') as file:
            file.write(
                f'# {self.appname}\n\n\n?\n\n## License\n\nGPLv3\n\n---\n')


    def initialise_vcs(self):
        try:
            if subprocess.run(['git', 'init', '-q']).returncode != 0:
                print('warning:  git init failed')
            if subprocess.run(['git', 'add', '.']).returncode != 0:
                print('warning:  git add . failed')
            if subprocess.run(['git', 'commit', '-q', '-m', 'started']
                    ).returncode != 0:
                print('warning:  git commit failed')
            subprocess.run(['git', 'branch', '-m', 'master', 'main'])
        except FileNotFoundError:
            print(f'warning:  failed to find git')


GLOBAL_INI = 'vbglobal.ini'
LOCAL_INI = 'vb.ini'
WIN = sys.platform.startswith('win')
GIO_RX = re.compile(r'\b(?:File\.|ZlibCompressor|Converter)')
VERSION_RX = re.compile(r'const\s+string\s+(?:[Vv]ersion|VERSION)'
                        r'\s*=\s*"(?P<version>[^"]+)"\s*;')
GIO = 'Gio'
START = r'\b(?P<pkg>'
END = r')\b'


@enum.unique
class Action(enum.Enum):
    CLEAN = 1
    BUILD = 2
    USAGE = 3
    INI_USAGE = 4
    VERSION = 5
    NEW = 6


@enum.unique
class New(enum.Enum):
    APP = 1
    GUI = 2
    LIB = 3

    @classmethod
    def names(klass):
        return [name for name in klass.__members__]


    @classmethod
    def from_name(klass, name):
        name = name.upper()
        for kind_name, kind in klass.__members__.items():
            if kind_name == name:
                return kind


@enum.unique
class Category(enum.Enum):
    GENERAL = 1
    PACKAGES = 2
    EXTRA_FILES = 3
    APP_TEMPLATE = 4
    GUI_TEMPLATE = 5
    LIB_TEMPLATE = 6


class Error(Exception):
    pass


Packages = dict(
    Gee='gee-0.8',
    Gio='gio-2.0',
    Gtk='gtk+-3.0',
    )

APP_TEMPLATE = '''\
// Copyright © #YEAR# #USER#. All rights reserved.
// License: GPLv3

const string APPNAME = "#APPNAME#";
const string VERSION = "0.1.0";

void main(string[] args) {
    stdout.printf("Hello %s v%s\\n", APPNAME, VERSION);
}
'''

GUI_TEMPLATE = '''\
// Copyright © #YEAR# #USER#. All rights reserved.
// License: GPLv3

const string APPNAME = "#APPNAME#";
const string VERSION = "0.1.0";

void main(string[] args) {
    Gtk.init(ref args);

    var window = new Gtk.Window();
    window.title = "Hello " + APPNAME + " v" + VERSION;
    window.window_position = Gtk.WindowPosition.CENTER;
    window.set_default_size(320, 240);
    window.destroy.connect(Gtk.main_quit);

    window.show_all();

    Gtk.main();
}
'''

LIB_TEMPLATE = '' # TODO

USAGE = '''\
vb.py [clean|help|version|[[quiet] [build] [console] [zip] ...]

With no arguments builds and runs the application.

Specifically, it compiles all .vala files in the current directory and
creates the ./appname executable (.\\dist\\appname.exe on Windows).
It assumes that there is one application in the directory.

appname is normally found in a .vala file (e.g., const string APPNAME = "...";)
which is recommended. However, if that isn't found appname is set to the
name of the one and only .vala file or if there are two or more .vala files
to the name of the parent directory or to the appname specified in the
vb.ini file if present (use 'help ini' for more on vb.ini files).

If packages are required (e.g., Gtk or Gee) these are auto-detected
and used in the compilation using default versions or the versions specified
in vb.ini if present and specified.

On Windows all the necessary dlls are copied to .\\dist alongside
appname.exe. Also if icon.ico or images\\icon.ico is present and rcedit.exe
is available, the icon is added to the executable. And any ExtraFiles (see
help ini) are also copied to .\\dist.

Once built the executable is then run.

...
    Any other arguments are passed to the executable if it is run

build -b --build
    Builds the executable as with no arguments but does not run it

clean -c --clean
    On Linux deletes the appname executable
    On Windows deletes the .\\dist subfolder

console -C --console
    Windows only: for Gtk applications allows console output;
    the default is not to

help -h --help
    Outputs this usage information and exits;
    Use 'help ini' for more about .ini files

new -n --new init [app|gui|lib] <NAME>
    Creates a new directory called NAME of type
    app (application), gui (GUI application), or lib (library).
    If the type isn't specified it is assumed to be app.

quiet -q --quiet
    Don't say what is being done at each step

version -v --version
   Outputs vb.py's version and exits

zip -z --zip
    Windows only: creates .\\dist\\appname.zip containing appname.exe and
    all the supporting dlls.
    If a version is found in a .vala file (e.g., const string VERSION = "...";)
    which is recommended, or if present in vb.ini then this is used in the
    .zip name, e.g., .\\dist\\appname-X.Y.Z.zip
'''

INI_USAGE = '''
vb.py contains sensible defaults so can be used without any configuration file.

However, creating a global vbglobal.ini file is recommended so that you
can set global default package versions and your own name, copyright, and
license defaults.

On Linux vbglobal.py will read its global configuration from the first of
these that it finds (if any): $HOME/.config/vbglobal.ini or
$HOME/.vbglobal.ini or $HOME/vbglobal.ini

On Windows the search is the same but using %HOME% or %USERPROFILE%.

Here is a vbglobal.ini file with all the defaults:

# Start of vbglobal.ini
[General]
winrcedit = C:/bin/rcedit.exe
winmsys2 = C:/bin/msys64

[Packages]
Gee = gee-0.8
Gio = gio-2.0
Gtk = gtk+-3.0

[AppTemplate]
// Copyright © #YEAR# #USER#. All rights reserved.
// License: GPLv3

const string APPNAME = "#APPNAME#";
const string VERSION = "0.1.0";

void main(string[] args) {
    stdout.printf("Hello %s v%s\\n", APPNAME, VERSION);
}

[GUITemplate]
// Copyright © #YEAR# #USER#. All rights reserved.
// License: GPLv3

const string APPNAME = "#APPNAME#";
const string VERSION = "0.1.0";

void main(string[] args) {
    Gtk.init(ref args);

    var window = new Gtk.Window();
    window.title = "Hello " + APPNAME + " v" + VERSION;
    window.window_position = Gtk.WindowPosition.CENTER;
    window.set_default_size(320, 240);
    window.destroy.connect(Gtk.main_quit);

    window.show_all();

    Gtk.main();
}
# End of vbglobal.ini

In the General section, on Windows the winrcedit entry is used for
rcedit.exe (if available), and the winmsys2 is used to find the msys2
folder.

For console applications the AppTemplate is used as the template and for GUI
applications, the GUITemplate. In both cases #YEAR# is replaced with this
year, #APPNAME# with the application's name given to the new command, and
#USER# with the user's username. No line of a template may start with [.

For individual projects vb.py will create a local vb.ini with three
sections, General, ExtraFiles, and Packages.

The General section can be used to set the application's name (appname) and
version: however, it is recommended that these are set in code as in the
AppTemplate and GUITemplate templates shown above. vb.py will read the .vala
files to find the appname and version when needed.

The ExtraFiles section is for Windows: any files listed here (globs are
supported) will be copied to .\dist.

The Packages section will be kept up to date by vb.py but may be edited.

vb.py assumes that the Packages section is always the last section.
'''


if __name__ == '__main__':
    main()
