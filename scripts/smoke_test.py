"""HTTP smoke check through Nginx; no model credentials or paid API calls."""
import argparse
import json
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    checks = [('/', None), ('/app.js', None), ('/styles.css', None),
              ('/healthz', None), ('/api/health', 'status'),
              ('/api/ready', 'status'), ('/api/projects', 'projects'),
              ('/api/knowledge/entries', 'entries'), ('/api/openapi.json', 'paths')]
    for path, key in checks:
        with urlopen(base + path, timeout=15) as response:
            assert response.status == 200, path
            content = response.read()
            if key:
                assert key in json.loads(content), path
            if path == '/':
                assert b'./app.js' in content
            print('PASS', path)


if __name__ == '__main__':
    main()
