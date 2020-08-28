#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import urllib.request
import argparse
import logging

GENERATOR_SCRIPT_URL = f'https://github.com/flatpak/flatpak-builder-tools/raw/master/cargo/flatpak-cargo-generator.py'

def get_latest_commit(url, branch):
    ref = f'refs/heads/{branch}'
    git_ls_remote = subprocess.run(['git', 'ls-remote', url, ref],
                                   check=True, text=True, stdout=subprocess.PIPE)
    commit, got_ref = git_ls_remote.stdout.split()
    assert got_ref == ref
    return commit

def generate_sources(app_source, clone_dir=None, generator_script=None):
    cache_dir = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))

    assert 'commit' in app_source
    if clone_dir is None:
        repo_dir = app_source['url'].replace('://', '_').replace('/', '_')
        clone_dir = os.path.join(cache_dir, 'flatpak-cargo-updater', repo_dir)
    if not os.path.isdir(os.path.join(clone_dir, '.git')):
        subprocess.run(['git', 'clone', '--recursive', app_source['url'], clone_dir],
                       check=True)
    git_rev_parse = subprocess.run(['git', 'rev-parse', 'HEAD'],
                                   cwd=clone_dir, check=True, text=True,
                                   stdout=subprocess.PIPE)
    if git_rev_parse.stdout.strip()[:7] != app_source['commit'][:7]:
        subprocess.run(['git', 'fetch'],
                       cwd=clone_dir, check=True)
        subprocess.run(['git', 'checkout', app_source['commit']],
                       cwd=clone_dir, check=True)

    if generator_script is None:
        generator_script = os.path.join(cache_dir, 'flatpak-cargo-updater', 'generator.py')
        urllib.request.urlretrieve(GENERATOR_SCRIPT_URL, generator_script)
        os.chmod(generator_script, 775)

    logging.info(f'Generation started with {generator_script}')
    generator_proc = subprocess.run([generator_script, '-o', '/dev/stdout',
                                    os.path.join(clone_dir, 'Cargo.lock')],
                                    check=True, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    generated_sources = json.loads(generator_proc.stdout)
    logging.info(f'Generation completed')

    return generated_sources

def commit_changes(app_source, files, on_new_branch=True, push_to=None):
    repo_dir = os.getcwd()
    title = f'Update to commit {app_source["commit"][:7]}'
    subprocess.run(['git', 'add', '-v', '--'] + files,
                   cwd=repo_dir, check=True)
    if on_new_branch:
        target_branch = f'update-{app_source["commit"][:7]}'
        subprocess.run(['git', 'checkout', '-b', target_branch],
                       cwd=repo_dir, check=True)
    else:
        git_branch = subprocess.run(['git', 'branch', '--show-current'],
                                    cwd=repo_dir, check=True, text=True,
                                    stdout=subprocess.PIPE)
        target_branch = git_branch.stdout.strip()

    subprocess.run(['git', 'commit', '-m', title],
                   cwd=repo_dir, check=True)

    git_rev_parse = subprocess.run(['git', 'rev-parse', 'HEAD'],
                                   cwd=repo_dir, check=True, text=True,
                                   stdout=subprocess.PIPE)
    new_commit = git_rev_parse.stdout.strip()
    logging.info(f'Commited {new_commit[:7]} on {target_branch}')

    if push_to is not None:
        subprocess.run(['git', 'push', push_to, target_branch],
                       cwd=repo_dir, check=True)

    return (target_branch, new_commit)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-g', '--generator', required=False)
    parser.add_argument('-d', '--clone-dir', required=False)
    parser.add_argument('-o', '--gen-output', default='generated-sources.json')
    parser.add_argument('-n', '--new-branch', action='store_true')
    parser.add_argument('-p', '--push-to', required=False)
    parser.add_argument('app_source_json')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    with open(args.app_source_json, 'r') as f:
        app_source = json.load(f)

    latest_commit = get_latest_commit(app_source['url'],
                                      app_source.get('branch', 'master'))

    if latest_commit == app_source['commit']:
        logging.info(f'Commit {app_source["commit"][:7]} is the latest')
        sys.exit(0)

    app_source.update({
        'commit': latest_commit
    })
    generated_sources = generate_sources(app_source,
                                         clone_dir=args.clone_dir,
                                         generator_script=args.generator)
    with open(args.app_source_json, 'w') as o:
        json.dump(app_source, o, indent=4)
    with open(args.gen_output, 'w') as g:
        json.dump(generated_sources, g, indent=4)

    branch, new_commit = commit_changes(app_source,
                                        files=[args.app_source_json, args.gen_output],
                                        on_new_branch=args.new_branch,
                                        push_to=args.push_to)
    logging.info(f'Created commit {new_commit[:7]} on branch {branch}')

if __name__ == '__main__':
    main()
