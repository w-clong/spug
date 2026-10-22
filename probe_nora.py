import gzip
import re
import urllib.request

BASE = 'http://192.168.10.240:4000'


def rpm_names():
    data = urllib.request.urlopen(BASE + '/rpm/myrepo/repodata/repomd.xml', timeout=20).read()
    href = re.search(rb'href="([^"]*primary[^"]*)"', data).group(1).decode()
    xml = gzip.decompress(urllib.request.urlopen(BASE + '/rpm/myrepo/' + href, timeout=30).read())
    return set(n.decode() for n in re.findall(rb'<name>([^<]+)</name>', xml))


def deb_names():
    raw = urllib.request.urlopen(BASE + '/deb/ubuntu/dists/noble/main/binary-amd64/Packages.gz', timeout=30).read()
    text = gzip.decompress(raw).decode('utf-8', 'ignore')
    return set(re.findall(r'^Package: (.+)$', text, re.M))


rpm = rpm_names()
deb = deb_names()
for name in ['sl', 'cowsay', 'htop', 'tree', 'ncdu', 'jq', 'lsof', 'iputils', 'curl']:
    print(name, 'rpm=', name in rpm, 'deb=', name in deb)
