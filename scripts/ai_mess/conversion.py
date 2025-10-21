#!/usr/bin/env python3
"""
conversion.py

Convert a JSON dictionary file (topology/dictionary) into AMPCS-style
XML dictionary files for commands, channels, and events.

Assumptions and heuristics:
- Input can be a JSON object (with top-level keys like 'commands','channels','events'),
  a JSON array of dictionary entries, or a JSON-lines file. Non-JSON lines are skipped.
- Entries are classified into commands/channels/events using common keys and heuristics
  (e.g., a 'type' field, or presence of 'opcode'/'id'/'display_text'/'severity').
- The output XML structure uses reasonable element names matching AMPCS schema filenames
  (CommandDictionary, ChannelDictionary, EvrDictionary). Fields in each entry are
  converted to child elements. Parameters (if present for commands) are nested.

This script does not perform RELAX NG validation; if you need strict schema validation,
provide the relevant schema and we can add validation steps.

Usage:
  python3 scripts/conversion.py -i <input.json> [-o outputs/cdict]

Outputs:
  Writes up to three files in the output directory:
    command_<basename>.xml
    channel_<basename>.xml
    evr_<basename>.xml

"""
import argparse
import json
import os
import re
import sys

try:
    from lxml import etree
except Exception:
    etree = None


def load_json(path):
    """Load JSON from file. Supports JSON, JSON array, or JSON-lines fallback."""
    with open(path, 'r') as f:
        text = f.read()
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        # try JSON-lines
        objs = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                objs.append(json.loads(line))
            except Exception:
                # skip lines that aren't JSON
                continue
        return objs


def ensure_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def classify_entries(data):
    """Return three lists: commands, channels, events (evrs).

    Uses several heuristics to find entries.
    """
    commands = []
    channels = []
    evrs = []

    # If dict with keys
    if isinstance(data, dict):
        # common top-level keys
        for k in data.keys():
            lk = k.lower()
            if 'command' in lk or 'cmd' in lk:
                commands.extend(ensure_list(data[k]))
            elif 'channel' in lk or 'telemetry' in lk:
                channels.extend(ensure_list(data[k]))
            elif 'evr' in lk or 'event' in lk or 'ev' in lk:
                evrs.extend(ensure_list(data[k]))
        # If still empty, maybe entries are under 'dict' or 'entries'
        if not (commands or channels or evrs):
            for k in ['dict', 'dictionary', 'entries', 'items']:
                if k in data and isinstance(data[k], (list, dict)):
                    return classify_entries(data[k])

    # If list of entries, classify each by heuristics
    if isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            # direct hints
            t = None
            for key in ('type', 'kind', 'category'):
                if key in entry:
                    t = str(entry[key]).lower()
                    break
            if t:
                if 'command' in t or 'cmd' in t:
                    commands.append(entry); continue
                if 'channel' in t or 'telemetry' in t:
                    channels.append(entry); continue
                if 'evr' in t or 'event' in t:
                    evrs.append(entry); continue

            # presence of known keys
            keys = set(entry.keys())
            if {'opcode', 'name'} & keys or 'op_code' in keys or 'cmd' in keys:
                commands.append(entry); continue
            if 'display_text' in keys or 'units' in keys or 'format' in keys or 'range' in keys:
                channels.append(entry); continue
            if 'severity' in keys or 'evr' in keys or 'message' in keys:
                evrs.append(entry); continue

            # fallback: if name contains 'cmd' or 'command'
            name = str(entry.get('name', '')).lower()
            if 'cmd' in name or 'command' in name:
                commands.append(entry); continue
            if 'chan' in name or 'channel' in name or 'tm_' in name:
                channels.append(entry); continue
            if 'evr' in name or 'event' in name:
                evrs.append(entry); continue

    return commands, channels, evrs


def clean_tag(name):
    # make XML-safe tag name: replace invalid chars with underscore, ensure starts with letter/_
    if not name:
        return 'field'
    s = re.sub(r'[^0-9A-Za-z_\-]', '_', str(name))
    if re.match(r'^[0-9\-]', s):
        s = '_' + s
    return s


def to_xml_element(root_name, items, item_tag):
    """Build an XML element tree for a dictionary type.

    If lxml is available return an lxml Element, otherwise return a string
    containing the XML.
    """
    if etree is not None:
        root = etree.Element(root_name)
        for entry in items:
            item_el = etree.SubElement(root, item_tag)
            if isinstance(entry, dict):
                for k, v in entry.items():
                    tag = clean_tag(k)
                    if isinstance(v, list):
                        parent = etree.SubElement(item_el, tag)
                        for vv in v:
                            child = etree.SubElement(parent, 'item')
                            child.text = str(vv)
                    elif isinstance(v, dict):
                        parent = etree.SubElement(item_el, tag)
                        for kk, vv in v.items():
                            child = etree.SubElement(parent, clean_tag(kk))
                            child.text = str(vv)
                    else:
                        child = etree.SubElement(item_el, tag)
                        child.text = str(v)
            else:
                item_el.text = str(entry)
        return root

    # Fallback: build a simple escaped XML string
    def esc(s):
        return (str(s)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))

    parts = [f'<?xml version="1.0" encoding="UTF-8"?>', f'<{root_name}>']
    for entry in items:
        parts.append(f'<{item_tag}>')
        if isinstance(entry, dict):
            for k, v in entry.items():
                tag = clean_tag(k)
                if isinstance(v, list):
                    parts.append(f'<{tag}>')
                    for vv in v:
                        parts.append(f'<item>{esc(vv)}</item>')
                    parts.append(f'</{tag}>')
                elif isinstance(v, dict):
                    parts.append(f'<{tag}>')
                    for kk, vv in v.items():
                        parts.append(f'<{clean_tag(kk)}>{esc(vv)}</{clean_tag(kk)}>')
                    parts.append(f'</{tag}>')
                else:
                    parts.append(f'<{tag}>{esc(v)}</{tag}>')
        else:
            parts.append(esc(entry))
        parts.append(f'</{item_tag}>')
    parts.append(f'</{root_name}>')
    return '\n'.join(parts)


def write_xml(tree_or_str, path):
    # Accept either an lxml element or string
    if etree is not None and isinstance(tree_or_str, etree._Element):
        xml_bytes = etree.tostring(tree_or_str, pretty_print=True, xml_declaration=True, encoding='utf-8')
        with open(path, 'wb') as f:
            f.write(xml_bytes)
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(str(tree_or_str))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Convert JSON dictionary to AMPCS-like XML dictionaries')
    parser.add_argument('-i', '--input', dest='input', required=True, help='Input JSON file (topology/dictionary)')
    parser.add_argument('-o', '--outdir', dest='outdir', default=os.path.join('outputs', 'cdict'), help='Output directory for XML dictionaries')
    parser.add_argument('--basename', dest='basename', help='Optional basename for output files')

    args = parser.parse_args(argv)

    data = load_json(args.input)
    if data is None:
        print('No JSON data found in', args.input)
        sys.exit(1)

    commands, channels, evrs = classify_entries(data)

    os.makedirs(args.outdir, exist_ok=True)
    base = args.basename if args.basename else os.path.splitext(os.path.basename(args.input))[0]

    written = []
    if commands:
        root = to_xml_element('CommandDictionary', commands, 'Command')
        path = os.path.join(args.outdir, f'command_{base}.xml')
        write_xml(root, path)
        written.append(path)

    if channels:
        root = to_xml_element('ChannelDictionary', channels, 'Channel')
        path = os.path.join(args.outdir, f'channel_{base}.xml')
        write_xml(root, path)
        written.append(path)

    if evrs:
        root = to_xml_element('EvrDictionary', evrs, 'Evr')
        path = os.path.join(args.outdir, f'evr_{base}.xml')
        write_xml(root, path)
        written.append(path)

    if not written:
        print('No commands, channels, or events found in input.')
    else:
        print('Wrote files:')
        for p in written:
            print('  ' + p)


if __name__ == '__main__':
    main()
