#!/usr/bin/env python3
import os
import sys
import shutil
import time
import signal
import fnmatch
from functools import partial
from multiprocessing import Process
from pathlib import Path
import argparse
from hashlib import md5
import socketserver
import http.server
import logging
import subprocess
import re
import inspect
from datetime import date, datetime

from markdown import markdown, inlinepatterns, Extension as MarkdownExtension
from jinja2 import Template, FileSystemLoader, Environment
from yaml import load, dump, load_all

from .appvars import APPDATA_LOCAL, PATHSEP
from .utils import UserExtension

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

logging.basicConfig(stream=sys.stdout, level=logging.CRITICAL)


class StrikeThroughExtension(MarkdownExtension):
    def extendMarkdown(self, md):
        md.inlinePatterns.register(
            inlinepatterns.SimpleTagPattern(
                r"(~{2})(.+?)(~{2})", # ~~ optionally anything at least once ~~
                "del"), "blogger-strikethrough", 100)

def server(port, directory):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with socketserver.TCPServer(("", port), handler) as httpd:
        logging.getLogger("Server").info(f"serving at port {port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            return

class DirectoryWatcher():
    def __init__(self, directory, ignore_patterns=None, init=True):
        self.directory = Path(directory)
        self.path_hash = dict()
        self.ignore_patterns = ignore_patterns
        self.logger = logging.getLogger(f"DirectoryWatcher")
        if init:
            self.dirty()

    def dirty(self):
        dirty = False
        for path in self.directory.glob("**/*"):
            if self.ignore_patterns:
                skip = False
                for pattern in self.ignore_patterns:
                    if fnmatch.fnmatch(str(path), pattern):
                        skip = True
                        break
                if skip:
                    self.logger.debug(f"Skipping {path}")
                    continue
            try:
                with path.open("rb") as f:
                    data = f.read()
            except PermissionError:
                continue
            h = md5(data).hexdigest()
            name = str(path.absolute())
            dirty = dirty or name not in self.path_hash or self.path_hash[name] != h
            self.path_hash[name] = h
        return dirty

class Post:
    def __init__(self, source_text, front_matter, body_text, metadata, rendered_text):
        self.source_text = source_text
        self.front_matter = front_matter
        self.body_text = body_text
        self.metadata = metadata
        self.rendered_text = rendered_text
        self.html = ""

def serialize_post(source_text):
    yaml_docs = source_text.split("---")
    if len(yaml_docs)>2:
        front_matter = yaml_docs[1]
        body_text = "".join(yaml_docs[2:])
    else:
        front_matter = None
        body_text = source_text
    try:
        metadata = next(load_all(source_text, Loader=Loader))
    except Exception as e:
        metadata = None
        logging.getLogger("main").error(e)
    return Post(source_text, front_matter, body_text, metadata, "")



class Main():
    def __init__(self, args):
        self.logger = logging.getLogger("main")
        if args.path and os.path.exists(args.path):
            self.working_directory = Path(os.path.abspath(args.path))
        else:
            self.working_directory = Path(os.path.abspath(os.getcwd()))
        if not self.working_directory.exists():
            self.logger.error(f"Given path: {self.working_directory} does not exist!")
            raise Exception("Bad main working directory!")
        self.app_data = APPDATA_LOCAL / self.working_directory.name
        if not self.app_data.exists():
            self.app_data.mkdir(parents=True)
        if hasattr(args, "output_dir") and args.output_dir:
            self.out_dir = Path(os.path.abspath(args.output_dir))
        else:
            self.out_dir = self.app_data / "_site"
        self.site_conf = self.working_directory / "site.yaml"
        self.templates_dir = self.working_directory / "templates"
        self.posts_dir = self.working_directory / "posts"
        self.drafts_dir = self.working_directory / "drafts"
        if not self.templates_dir.exists():
            # TODO (owen): I think for commands like "draft and publish we don't need to check this but not sure if moving it to compile will break stuff
            self.logger.error("Can't work without templates")
            self.logger.critical("Specified or current working directory is not properly formatted to use blogger. Please see documentation (TODO (owen): Write docs)")
            sys.exit(-1)
        self.jinja_env = Environment(loader=FileSystemLoader([str(self.templates_dir), str(self.posts_dir), str(self.working_directory)]))
        if self.site_conf.exists():
            with self.site_conf.open() as infstream:
                self.site_data = load(infstream, Loader=Loader)
        if self.site_data and "ignore-patterns" in self.site_data:
            self.ignore_patterns = self.site_data["ignore-patterns"]
        else:
            self.ignore_patterns = []
        assert(self.templates_dir.exists() and self.templates_dir.is_dir())
        self.load_user_extensions()

    def load_site_data(self):
        if self.site_conf.exists():
            with self.site_conf.open() as infstream:
                self.site_data = load(infstream, Loader=Loader)
        if self.site_data and "ignore-patterns" in self.site_data:
            self.ignore_patterns = self.site_data["ignore-patterns"]
        else:
            self.ignore_patterns = []

    def run(self, args):
        self.compile(args)
        server_process = Process(target=server, args=(args.port, self.out_dir))
        server_process.start()
        self.dir_watcher = DirectoryWatcher(self.working_directory, ignore_patterns=self.ignore_patterns)
        quit = False
        starttime = time.time()
        every = 1
        def sig_int(sig, frame):
            nonlocal quit
            server_process.terminate()
            quit = True
        def sig_term(sig, frame):
            nonlocal quit
            server_process.terminate()
            quit = True
        signal.signal(signal.SIGINT, sig_int)
        signal.signal(signal.SIGTERM, sig_term)
        while not quit:
            deltatime = time.time() - starttime
            if deltatime > every:
                if self.dir_watcher.dirty():
                    # try and catch so the thing keeps going
                    try:
                        self.load_site_data()
                        self.compile(args)
                    except Exception as e:
                        self.logger.critical(f"Unhandled error compiling site. Will keep watching but this change did not compile successfully")
                        self.logger.exception(e)
                starttime = time.time()
        self.logger.info("Run terminated")

    def compile(self, args):
        self.initialize_user_extensions()
        templates_dict = {}
        posts_dict = {}
        def read_file(f, dic, root=None, serializer = lambda d: d):
            with f.open() as inf:
                if root:
                    name = str(f.relative_to(root))
                else:
                    name = str(f.absolue())
                dic[name] = serializer(inf.read())
        def read_dir(d, dic, root=None, file_ext=None, serializer = lambda d: d):
            assert(d.is_dir())
            exclude_paths = []
            for pattern in self.ignore_patterns:
                exclude_paths.extend(d.rglob(pattern))
            for f in d.iterdir():
                if f in exclude_paths:
                    continue
                if f.is_file():
                    if file_ext is None:
                        read_file(f, dic, root, serializer=serializer)
                    elif f.name.endswith(file_ext):
                        read_file(f, dic, root, serializer=serializer)
                else:
                    read_dir(f, dic, file_ext = file_ext, serializer=serializer)
        read_dir(self.templates_dir, templates_dict, root=self.templates_dir)
        if(self.posts_dir.exists()):
            read_dir(self.posts_dir, posts_dict, root=self.posts_dir, file_ext=".md", serializer=serialize_post)
        if args.drafts:
            if self.drafts_dir.exists():
                read_dir(self.drafts_dir, posts_dict, root=self.drafts_dir, file_ext=".md", serializer=serialize_post)
            else:
                self.logger.critical(f"Cannot compile with drafts! {self.drafts_dir} does not exists.")
        for name, post in posts_dict.items():
            self.logger.info(f"Rendering post {name}")
            for extension in self.user_extension_instances:
                extension.pre_render_post(name, post)
            template = self.jinja_env.from_string(post.body_text)
            if post.metadata:
                post.rendered_text = template.render(site=self.site_data, **post.metadata)
            else:
                post.rendered_text = template.render(site=self.site_data)
            markdown_extensions = [StrikeThroughExtension()]
            markdown_extensions_configurations = {}
            if self.site_data and "markdown-extensions" in self.site_data:
                markdown_extensions.extend(self.site_data["markdown-extensions"])
            if self.site_data and "markdown-extensions-configurations" in self.site_data:
                markdown_extensions_configurations.update(**self.site_data["markdown-extensions-configurations"])
            if post.metadata and "markdown-extensions" in post.metadata:
                markdown_extensions.extend(post.metadata["markdown-extensions"])
            if post.metadata and "markdown-extensions-configurations" in post.metadata:
                markdown_extensions_configurations.update(**post.metadata["markdown-extensions-configurations"])
            post.html = markdown(post.rendered_text, extensions=markdown_extensions, extensions_configs=markdown_extensions_configurations)
            post.name = name
            if "title" in post.metadata:
                post.toc = post.metadata["title"].replace(" ", "-")
            else:
                post.toc = post.name.strip(".md").replace(" ", "-")
            # note: this makes using the metadata easier from templates
            for key, value in post.metadata.items():
                setattr(post, key, value)
            # run user extensions on each post
            for extension in self.user_extension_instances:
                extension.post_render_post(name, post)
        for name, template in templates_dict.items():
            template = self.jinja_env.get_template(name)
            def run_user_extensions_for_template():
                for extension in self.user_extension_instances:
                    result = extension.should_skip_template(name, template, posts_dict)
                    if result:
                        self.logger.info(f"{extension.__class__.__name__} has skipped template {name}")
                    yield result
            if any([r for r in run_user_extensions_for_template()]): # any user extesion can shortcut the template rendering
                self.logger.info(f"Skipping template {name}")
                continue
            self.logger.info(f"Rendering template {name}")
            rendered = template.render(site=self.site_data, posts=list(posts_dict.values()))
            if not self.out_dir.exists():
                self.out_dir.mkdir(parents=True)
            out = self.out_dir/name
            self.logger.info(f"Writing rendered template to {out}")
            with out.open("w", encoding="utf-8") as outf:
                outf.write(rendered)
        if self.site_data and "copy-paths" in self.site_data:
            copy_path_names = self.site_data["copy-paths"]
            assert(type(copy_path_names) is list)
            for path_name in copy_path_names:
                src_path = self.site_conf.parent / path_name
                dst_path = self.out_dir / path_name
                if src_path.is_dir():
                    self.logger.info(f"Copying {src_path}{PATHSEP} to {dst_path}{PATHSEP}")
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*self.ignore_patterns))
                else:
                    ignore=False
                    for ignore_pattern in self.ignore_patterns:
                        if fnmatch.fnmatch(path_name, ignore_pattern):
                            ignore=True
                            self.logger.info(f"Ignoring {path_name}")
                            break
                    if ignore:
                        continue
                    else:
                        self.logger.info(f"Copying {src_path} to {dst_path}")
                        shutil.copyfile(src_path, dst_path)
        for extension in self.user_extension_instances:
            extension.finalize()

    def load_user_extensions(self):
        """
        NOTES:
        2 user extensions on the same site cannot have conflicting site-package requirements
        """
        # path is path to top level user folder (i.e. the top level site folder)
        working_dir = Path(self.working_directory)
        assert(working_dir.exists())
        requirements_path = working_dir / "requirements.txt"
        if not requirements_path.exists() and (working_dir/"extensions").is_dir():
            requirements_path = working_dir / "extensions"/"requirements.txt"
        venv_path = self.app_data / ".venv"
        lib_path = venv_path / "Lib" / "site-packages" if sys.platform == "win32" else venv_path / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        if requirements_path.exists():
            do_install = False
            self.logger.debug(f"Found extension-requirements at {requirements_path}")
            # check to see if site local venv exists and if requirements already installed
            if venv_path.exists():
                self.logger.debug("Existing venv found")
                if lib_path.exists():
                    self.logger.debug("Existing site-packages found")
                    sys.path.append(str(lib_path))
                    import pkg_resources # late import insures that the site local venv site-packages are read by pkg_resources
                    with requirements_path.open("r") as inf:
                        requires = [str(r) for r in pkg_resources.parse_requirements(inf.read())]
                    try:
                        pkg_resources.require(requires) # throws if requirements met in current path
                        self.logger.debug("All requirements satisfied. Skipping installation")
                        do_install = False # redundant but informative
                    except (pkg_resources.DistributionNotFound, pkg_resources.VersionConflict) as err:
                        reason = re.sub(r'((?<=[a-z])[A-Z]|(?<!\A)[A-Z](?=[a-z]))', r' \1', err.__class__.__name__)
                        self.logger.error(f"Requirement {err.req} not met. Reason: \"{reason}\"")
                        do_install = True
                    # TODO (owen): there are 2 more possible exceptions "UnkownExtra" and "ExtractionError" I've never seen these in common practace and don't know what they mean but I should probably handle them here
                else:
                    self.logger.debug("No site packages found in existing venv")
                    do_install = True
            else:
                # make a new venv in the user folder
                self.logger.debug(f"Making new venv for extension-requirements at {venv_path}")
                subprocess.check_call([sys.executable, "-m", "venv", str(venv_path)])
                do_install = True
            local_python = venv_path / "Scripts" / "python.exe" if sys.platform == "win32" else venv_path / "bin" / "python"
            assert(local_python.exists())
            if do_install:
                # install user extension requirements to site local virtualenv
                self.logger.debug(f"Installing extension requirements to site venv")
                cmd = [str(local_python), "-m", "pip", "install", "-r", str(requirements_path)]
                self.logger.debug(f"Running subprocess: {' '.join(cmd)}")
                with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
                    for c in iter(proc.stdout.readline,  b''):
                        print(c.decode("utf-8"))
                    proc.communicate()
            # append the user site-packages to the current executable path (this is needed to successfully import user extension module)
            assert(lib_path.exists())
            sys.path.append(str(lib_path))
        sys.path.append(str(working_dir)) # add user folder to system path
        # TODO (owen) DOCS: Document that the extension module should me named "extensions" and that it can be any python importable, i.e. package or module
        import extensions # initial import loads the "extensions" module cache entry used on the next line
        # use inspect to get all classes that subclass UserExtension
        self.user_extension_classes = [cls for name, cls in inspect.getmembers(sys.modules["extensions"]) if inspect.isclass(cls) and issubclass(cls, (UserExtension)) and cls is not UserExtension]

    def initialize_user_extensions(self):
        # initialize instance list with list of fresh instances
        self.user_extension_instances = [e(logging.getLogger(f"{e.__name__}"), self.working_directory, self.out_dir, self.site_data, self.jinja_env) for e in self.user_extension_classes]

    def post(self, args):
        # iterate drafts and prompt user for selection, then confirm title and date and move to the posts folder with correct name (YYYY-MM-DD-title.md)
        exclude_paths = []
        for pattern in self.ignore_patterns:
            exclude_paths.extend(self.drafts_dir.rglob(pattern))
        drafts = [d for d in self.drafts_dir.iterdir() if d not in exclude_paths]
        print(f"Found {len(drafts)} drafts:")
        for index, d in enumerate(drafts):
            print(f"\t {index+1}) {d.name}")
        index = 0
        while True:
            index = input(f"Which would you like to post? [1-{len(drafts)} or q to quit]: ")
            if index == "q":
                sys.exit(0)
            try:
                index = int(index)
            except ValueError:
                self.logger.critical("Invalid input.")
                continue
            if index > len(drafts) or index < 1:
                self.logger.critical(f"{index} is invalid. Out of range!")
                continue
            break
        draft = drafts[index-1]
        post = None
        with draft.open() as inf:
            post = serialize_post(inf.read())
        # TODO (owen): verify post date and title and move file to posts/ directory
        def get_answer(yn_question):
            while True:
                resp = input(f"{yn_question} [y/n]: ")
                if resp in ["y", "Y", "n", "N"]:
                    return resp.lower() == "y"
        def validate(validate_what, data):
            print(f"Current {validate_what} is \"{data}\"")
            return get_answer("Is this ok?")
        while not validate("title", post.metadata["title"]):
            post.metadata["title"] = input("Enter title: ")
        while not validate("date", post.metadata["date"]):
            while True:
                d = input("Enter date (YYYY-MM-DD) or \"[t]oday\" for local clock date: ")
                if d.lower() in ["t", "today"]:
                    post.metadata["date"] = date.today()
                else:
                    try:
                        dt = datetime.strptime(d, "%Y-%m-%d")
                    except ValueError:
                        self.logger.critical("Invalid date fromat")
                        continue
                    post.metadata["date"] = dt.date()
                break
        title = post.metadata["title"].lower().replace(" ", "-")
        punc_reg = r"[^\w|^\-\s]"
        title = re.sub(punc_reg, "", title);
        filename = f"{post.metadata['date']}-{title}.md"
        f = self.posts_dir / filename
        post.front_matter = dump(post.metadata)
        print(f"Writing post to {f}")
        if f.exists():
            self.logger.critical(f"{f} already exists in the post/ folder. Cannnot over write post with this utility.")
            sys.exit(1)
        assert(not f.exists())
        with f.open('w') as outf:
            outf.write("---\n")
            outf.write(post.front_matter)
            outf.write("---\n")
            outf.write("\n")
            outf.write(post.body_text)
        if get_answer("Post written. Delete draft?"):
            print(f"Deleteing {draft}")
            os.remove(draft)

    def draft(self, args):
        # TODO: make a new markdown file named according to our scheme (YYYY-MM-DD-Title-DRAFT.md) or something.
        # with front matter prefilled (title, date, etc) and put it in the draft folder
        today = date.today().strftime('%Y-%m-%d')
        title = args.title or "draft"
        FRONTMATTER = f"""---
date: {today}
title: "{title}"
---"""
        name = f"{today}-{title}.md"
        out = self.drafts_dir / name
        if not out.parent.exists():
            out.parent.mkdir(parents=True)
        index = 0
        while out.exists():
            index += 1
            name = f"{today}-{title}({index}).md"
            out = self.drafts_dir / name
        self.logger.info(f"Creating draft file {out}")
        with out.open("w", encoding="utf-8") as outf:
            outf.write(FRONTMATTER)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compiles a static blog site from markdown files and templates and comes with useful utilities for blog writing")
    subparsers = parser.add_subparsers(dest="subparsers", title="commands")
    parser.add_argument("path", default=None)
    parser.add_argument("-v", "--verbose", action="count", default=0)

    out_arg_help = f"If chosen command outputs files place them in the give directory. Default is {APPDATA_LOCAL}{PATHSEP}[SITE_DIRECTORY_NAME]{PATHSEP}_site."
    # run
    run_parser = subparsers.add_parser("run", help="Compile the site and serve it locally on a give port or default:8000. Watch the site files and recompile changes")
    run_parser.add_argument("-p", "--port", type=int, default=8000)
    run_parser.add_argument("-d", "--drafts", action="store_true", help=f"Include the {PATHSEP}drafts directory of the site")
    run_parser.add_argument("-o", "--output-dir", help=out_arg_help)

    # compile
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("-d", "--drafts", action="store_true", help=f"Include the {PATHSEP}drafts directory of the site")
    compile_parser.add_argument("-o", "--output-dir", help=out_arg_help)

    # draft
    draft_parser = subparsers.add_parser("draft")
    draft_parser.add_argument("-t", "--title", default="draft", help="The title of the draft post. This can be changed later before you post")

    # post
    post_parser = subparsers.add_parser("post")

    def run(args):
        main = Main(args)
        main.run(args)
    def draft(args):
        main = Main(args)
        main.draft(args)
    def compile(args):
        main = Main(args)
        main.compile(args)
    def post(args):
        main = Main(args)
        main.post(args)

    draft_parser.set_defaults(func=draft)
    run_parser.set_defaults(func=run)
    compile_parser.set_defaults(func=compile)
    post_parser.set_defaults(func=post)
    args = parser.parse_args()
    log_level = logging.CRITICAL
    levels = [logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG]
    if args.verbose:
        verbosity = max(0, min(args.verbose, len(levels)-1))
        log_level = levels[verbosity]
        logging.getLogger().setLevel(log_level)
    else:
        print(f"Log level set to {logging.getLevelName(logging.root.level)}. You may not be seeing everything you want. Use -v, -vv, -vvv, or -vvvv to see more log messages")
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(0)
