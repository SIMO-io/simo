#!/usr/bin/env python
import sys
import os
import shutil
import simo
from django.template import Context, Engine
from django.core.management.utils import get_random_secret_key


def copy_template(to_directory='/etc/SIMO'):
    template_file_extensions = ['.py', '.conf']

    context = Context({
        'secret_key': get_random_secret_key(),
        'project_dir': to_directory,
        'base_dir': to_directory
    }, autoescape=False)
    template_dir = os.path.join(
        os.path.dirname(simo.__file__), '_hub_template'
    )
    prefix_length = len(template_dir) + 1
    for root, dirs, files in os.walk(template_dir):
        relative_dir = root[prefix_length:]
        target_dir = os.path.join(to_directory, relative_dir)
        os.makedirs(target_dir, exist_ok=True)
        for filename in files:
            if filename.endswith(('.pyo', '.pyc', '.py.class')):
                # Ignore some files as they cause various breakages.
                continue
            old_path = os.path.join(root, filename)
            new_path = os.path.join(target_dir, filename)
            os.makedirs(target_dir, exist_ok=True)
            fn, file_extension = os.path.splitext(new_path)
            if file_extension in template_file_extensions:
                with open(old_path, encoding='utf-8') as template_file:
                    content = template_file.read()
                template = Engine().from_string(content)
                content = template.render(context)
                with open(new_path, 'w', encoding='utf-8') as new_file:
                    new_file.write(content)
            else:
                shutil.copyfile(old_path, new_path)
            shutil.copymode(old_path, new_path)
        for dirname in dirs[:]:
            if dirname.startswith('.') or dirname == '__pycache__':
                dirs.remove(dirname)
            else:
                os.makedirs(os.path.join(root, dirname), exist_ok=True)



if __name__ == "__main__":
    sys.exit(copy_template())
