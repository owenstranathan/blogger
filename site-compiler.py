#!/usr/bin/env python3
import os
import sys
import shutil
from pathlib import Path
import argparse

from markdown import markdown
from jinja2 import Template, FileSystemLoader, Environment
from yaml import load, dump, load_all
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper


# TODO: read from an ignore file or something
ignore_patterns = ["*.swp"]

class Post:
    def __init__(self, source_text, front_matter, body_text, metadata, rendered_text):
        self.source_text = source_text
        self.front_matter = front_matter
        self.body_text = body_text
        self.metadata = metadata
        self.rendered_text = rendered_text
        self.html = ""

def serialize_post(source_text):
    # todo get front matter, parse it and put everything in a named tuple
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
        print(e)
    return Post(source_text, front_matter, body_text, metadata, "")


def main():
    parser = argparse.ArgumentParser(description="Compiles a static site from markdown files and templates")
    parser.add_argument("path", default=None)
    parser.add_argument("-o", "--output-dir", default="_site")
    parser.add_argument("-d", "--drafts", default=None)
    args = parser.parse_args()
    if args.path and os.path.exists(args.path):
        working_directory = Path(os.path.abspath(args.path))
    else:
        working_directory = Path(os.path.abspath(os.getcwd()))
    out_dir = Path(os.path.abspath(args.output_dir))
    site_conf = working_directory / "site.yaml"
    templates_dir = working_directory / "templates"
    posts_dir = working_directory / "posts"
    drafts_dir = None
    if args.drafts:
        drafts_dir = Path(os.path.abspath(args.drafts))
    if not templates_dir.exists():
        print("Can't work without templates")
        sys.exit(-1)
    jinja_env = Environment(loader=FileSystemLoader([str(templates_dir), str(posts_dir)]))
    if site_conf.exists():
        with site_conf.open() as infstream:
            site_data = load(infstream, Loader=Loader)
    assert(templates_dir.exists() and templates_dir.is_dir())
    assert(posts_dir.exists() and posts_dir.is_dir())
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
        for pattern in ignore_patterns:
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
    read_dir(templates_dir, templates_dict, root=templates_dir)
    read_dir(posts_dir, posts_dict, root=posts_dir, file_ext=".md", serializer=serialize_post)
    if drafts_dir:
        read_dir(drafts_dir, posts_dict, root=drafts_dir, file_ext=".md", serializer=serialize_post)

    for name, post in posts_dict.items():
        print(f"Rendering post {name}")
        post_metadata = post.metadata
        template = jinja_env.from_string(post.body_text)
        if post.metadata:
            post.rendered_text = template.render(site=site_data, **post.metadata)
        else:
            post.rendered_text = template.render(site=site_data)
        markdown_extensions = []
        if site_data and "markdown-extensions" in site_data:
            markdown_extensions.extend(site_data["markdown-extensions"])
        if post.metadata and "markdown-extensions" in post.metadata:
            markdown_extensions.extend(post.metadata["markdown-extensions"])
        post.html = markdown(post.rendered_text, extensions=markdown_extensions)
        post.name = name
        if "title" in post.metadata:
            post.toc = post.metadata["title"].replace(" ", "-")
        else:
            post.toc = post.name.strip(".md").replace(" ", "-")
        # note: this makes using the metadata easier from templates
        for key, value in post.metadata.items():
            setattr(post, key, value)

    for name, template in templates_dict.items():
        print(f"Rendering template {name}")
        template = jinja_env.get_template(name)
        rendered = template.render(site=site_data, posts=list(posts_dict.values()))
        if not out_dir.exists():
            out_dir.mkdir(parents=True)
        out = out_dir/name
        print(f"Writing rendered template to {out}")
        with out.open("w", encoding="utf-8") as outf:
            outf.write(rendered)
    if site_data and "copy-paths" in site_data:
        copy_path_names = site_data["copy-paths"]
        assert(type(copy_path_names) is list)
        for path_name in copy_path_names:
            src_path = site_conf.parent / path_name
            dst_path = out_dir / path_name
            if src_path.is_dir():
                print(f"Copying {src_path}{os.path.sep} to {dst_path}{os.path.sep}")
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            else:
                print(f"Copying {src_path} to {dst_path}")
                shutil.copyfile(src_path, dst_path)
    print("done")


if __name__ == "__main__":
    main()
