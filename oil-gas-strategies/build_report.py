"""Embed results/report_page_data.json into report_template.html.
Writes ../oil-gas-trading-strategies.html (standalone page for GitHub Pages) and, if given, an artifact fragment."""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KEEP = ['summary', 'costs', 'bootstrap_mc', 'equity', 'case2026', 'ng', 'families', 'heat', 'random', 'sides', 'straddle']


def clean(x):
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, float):
        return None if not math.isfinite(x) else round(x, 5)
    return x


def build(fragment_out=None):
    data = json.load(open(os.path.join(HERE, 'results', 'report_page_data.json')))
    data = clean({k: data[k] for k in KEEP})
    payload = json.dumps(data, allow_nan=False, separators=(',', ':')).replace('<', '\\u003c')
    tpl = open(os.path.join(HERE, 'report_template.html'), encoding='utf-8').read()
    assert tpl.count('__DATA__') == 1
    frag = tpl.replace('__DATA__', payload)
    page = ('<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + frag + '\n</html>\n')
    out = os.path.join(os.path.dirname(HERE), 'oil-gas-trading-strategies.html')
    open(out, 'w', encoding='utf-8').write(page)
    print('wrote', out, f'{len(page) / 1e3:.0f} KB')
    if fragment_out:
        open(fragment_out, 'w', encoding='utf-8').write(frag)
        print('wrote', fragment_out)


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else None)
