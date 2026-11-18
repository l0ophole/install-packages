#!/usr/bin/env python3
import os
import requests
from bs4 import BeautifulSoup
import yaml
from urllib.parse import urlparse
import json
from sys import exit


class SolutionItem:
    _filename = None
    _cached_file = None
    _download_url = None
    def __init__(self, filename=None, cached_file=None, download_url=None):
        super().__init__()
        if filename:
            self._filename = filename
        if cached_file:
            self._cached_file = cached_file
        if download_url:
            self._download_url = download_url

    def filename(self, filename=None):
        if not filename:
            return self._filename
        self._filename = filename

    def cached_file(self, cached_file=None):
        if not cached_file:
            return self._cached_file
        self._cached_file = cached_file

    def download_url(self, download_url=None):
        if not download_url:
            return self._download_url
        self._download_url = download_url


def get_install_solution(pkgs):
    args = ['pacman', '-S', '--print-format=' + '%n %l']
    args.extend(pkgs)
    from subprocess import check_output, STDOUT, CalledProcessError
    try:
        output = check_output(args=args, shell=False, universal_newlines=True, stderr=STDOUT)
    except CalledProcessError:
        import traceback
        print(f"get_install_solution(): ERROR: {traceback.format_exc()}")
        return
    for line in output.split('\n'):
        line = line.strip().rstrip('\n')
        if not line:
            continue
        parts = line.split(' ')
        pkg = parts[0]
        uri = ' '.join(parts[1:])
        yield (pkg, uri)

def load_headers(file_path):
    # Headers are optional. If no headers file exists, return {} so the
    # Archive requests go out with the default requests headers instead
    # of crashing. A headers file is YAML mapping header names to values.
    if not file_path or not os.path.isfile(file_path):
        return {}
    with open(file_path, 'r') as f:
        data = f.read()
    data = data.strip().rstrip('\n')
    loaded = yaml.safe_load(data)
    return loaded if isinstance(loaded, dict) else {}

def find_headers_file():
    # Look for a headers.yaml in a few sensible places, in order:
    #   1. $INSTALL_PACKAGES_HEADERS
    #   2. next to this script
    #   3. ~/.config/install-packages/headers.yaml
    #   4. ~/scripts/headers.yaml (original author's layout)
    candidates = [
        os.environ.get("INSTALL_PACKAGES_HEADERS"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "headers.yaml"),
        os.path.expanduser("~/.config/install-packages/headers.yaml"),
        os.path.expanduser("~/scripts/headers.yaml"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None

def download(url,filename):
    import requests
    resp = requests.get(url, allow_redirects=True)
    if resp.status_code >= 400:
        print(f"Download error: {resp.status_code}")
        return False, None
    with open(filename, 'wb') as fptr:
        fptr.write(resp.content)
    return True, filename

def install(filename):
    args = ['sudo', 'pacman', '-U', filename, '--noconfirm', "--overwrite=" + "*"]
    from subprocess import check_output, STDOUT, CalledProcessError
    try:
        output = check_output(args=args, shell=False, universal_newlines=True, stderr=STDOUT)
        # print(f"="*26)
        for line in output.split('\n'):
            print(line)
        # print(f"="*26)
        return True, filename
    except CalledProcessError:
        print(f"pacman reported an error while attempting to install package")
        return False, filename

def install_from_archive(solution_item):
    wanted_filename = solution_item.filename()
    pkgname = '-'.join(wanted_filename.split('-')[:-3])
    #cached_file = solution_item.cached_file()
    #download_url = solution_item.download_url()
    headers_file = find_headers_file()
    pkgindex = pkgname[0]
    ala_base_url = "https://archive.archlinux.org/packages"
    ala_host_addr = urlparse(ala_base_url).netloc
    headers = load_headers(headers_file)
    url = '/'.join([ala_base_url, pkgindex])
    resp = requests.get(url=url, headers=headers, allow_redirects=True)
    soup = BeautifulSoup(resp.text, 'html.parser')
    links = soup.find_all('a')
    link_pkgname = None
    link_href = None
    for i in links:
        link_pkgname = i.text
        if link_pkgname.endswith('/'):
            link_pkgname = link_pkgname[0:-1]
        if link_pkgname != pkgname:
            continue
        link_href = i['href']
        break
    if not link_href:
        print(f"ERROR: Package {pkgname} was not found in the Arch Linux Archive index.")
        return False
    parsed = urlparse(link_href)
    filename = parsed.path
    second_url = '/'.join([ala_base_url, pkgindex, link_href])
    resp2 = requests.get(url=second_url, headers=headers, allow_redirects=True)
    soup2 = BeautifulSoup(resp2.text, 'html.parser')
    soup2_links = soup2.find_all('a')
    file_url = None
    import urllib.parse as urllib_parse
    ignore_extensions = ['sig']
    version_tuple = None
    for link in soup2_links:
        link_url = link['href']
        parsed_url = urlparse(link_url)
        link_path = parsed_url.path
        link_filename = link_path.split('/')[-1]
        link_filename_extension = link_filename.split('.')[-1].lower()
        if (not link_filename) or (link_filename_extension in ignore_extensions):
            continue
        link_filename = urllib_parse.unquote(link_filename)
        if second_url.endswith('/'):
            file_url = ''.join([second_url, link_url])
        else:
            file_url = '/'.join([second_url, link_url])
        if link_filename == wanted_filename:
            version_tuple = {'filename': link_filename, 'url': file_url}
            break
    if not version_tuple:
        print(f"ERROR: File {wanted_filename} was not found in the Arch Linux Archive for package {pkgname}.")
        return False
    filename = version_tuple.get('filename')
    file_url = version_tuple.get('url')
    if not file_url:
        print(f"ERROR: Could not find file in page links.")
        return False
    success, downloaded_file = download(file_url, filename)
    if not success:
        print(f"ERROR: Could not download file: {downloaded_file}")
        return False
    success, install_file = install(downloaded_file)
    if not success:
        print(f"ERROR: Package {pkgname} failed to install. ({install_file})")
        return False
    print(f"Package {pkgname} was installed successfully.")
    return True

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('packages', action='store', type=str, nargs='*')
args = parser.parse_args()

# from multiprocessing import Manager
# manager = Manager()
# q = manager.Queue()

cache_dir = '/var/cache/pacman/pkg'
pacman_config_path = '/etc/pacman.conf'

with open(pacman_config_path, 'r') as f:
    lines = f.readlines()

for l in lines:
    l = l.strip().rstrip('\n')
    if (not l) or l.startswith('#'):
        continue
    p = l.split(' ')
    if p[0] != 'CacheDir':
        continue
    cache_dir = l.split('=')[1]
    cache_dir = cache_dir.strip()

print('CacheDir: {}'.format(cache_dir))

install_solution = list(get_install_solution(args.packages))

total_items = len(install_solution)

for n, (pkg, uri) in enumerate(install_solution):
    print(f"Installing package {n+1} of {total_items}...")
    pkg_filename = uri.split('/')[-1]
    if uri.startswith("file://"):
        cached_file = uri[7:]
        download_url = None
    else:
        cached_file = None
        download_url = uri

    solution_item = SolutionItem(filename=pkg_filename,cached_file=cached_file,download_url=download_url)

    if not install_from_archive(solution_item):
        print(f"Not continuing due to install failure")
        break
