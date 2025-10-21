#!/usr/bin/env python3
"""
Convert a JSON (lines or array) file to XML using json2xml and optionally validate against an XSD.

Usage:
  python scripts/convert_json_to_xml.py -i data/fprime_cmds_chan1.json
  python scripts/convert_json_to_xml.py -i data/fprime_cmds_chan1.json -x schema.xsd

The script writes output to outputs/json_responses/<input_basename>.xml
"""
import argparse
import json
import os
import sys
from datetime import datetime

try:
    from json2xml import json2xml
    from json2xml.utils import readfromjson
except Exception:
    json2xml = None

try:
    from lxml import etree
except Exception:
    etree = None


def load_json_objects(path):
    """Load JSON objects from a file. Supports JSONL (one JSON per line) or a JSON array/file."""
    objs = []
    with open(path, 'r') as f:
        data = f.read().strip()
        if not data:
            return objs
        # Try parsing as array/object first
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list):
                return parsed
            else:
                return [parsed]
        except Exception:
            # fallback to JSON lines
            for line in data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    objs.append(json.loads(line))
                except Exception:
                    # skip non-json lines
                    continue
    return objs


def convert_to_xml(objs, root_name='root', item_name='item'):
    """Convert list of JSON objects to an XML string."""
    # Prefer building XML with lxml for predictable structure
    if etree is not None:
        root = etree.Element(root_name)
        for obj in objs:
            item_el = etree.SubElement(root, item_name)
            if isinstance(obj, dict):
                for k, v in obj.items():
                    # convert value to text
                    child = etree.SubElement(item_el, k)
                    child.text = str(v)
            else:
                # non-dict items become text nodes
                item_el.text = str(obj)
        # pretty print
        xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='utf-8')
        return xml_bytes.decode('utf-8')

    # Fallback to json2xml if lxml isn't available
    wrapper = {root_name: {item_name: objs}}
    if json2xml is None:
        raise RuntimeError('Either lxml or json2xml package is required. Install from requirements.txt')
    j2x = json2xml.Json2xml(wrapper, wrapper=True)
    xml_str = j2x.to_xml()
    return xml_str


def validate_xml(xml_bytes, xsd_path):
    if etree is None:
        raise RuntimeError('lxml is required for XSD validation. Add lxml to requirements.')
    xml_doc = etree.fromstring(xml_bytes)
    with open(xsd_path, 'rb') as f:
        schema_doc = etree.parse(f)
    schema = etree.XMLSchema(schema_doc)
    valid = schema.validate(xml_doc)
    if not valid:
        # collect errors
        errors = [str(e.message) for e in schema.error_log]
        return False, errors
    return True, []


def main(argv=None):
    parser = argparse.ArgumentParser(description='Convert JSON to XML')
    parser.add_argument('-i', '--input', dest='input_file', required=True, help='Input JSON file (json or jsonl)')
    parser.add_argument('-o', '--output', dest='output_file', help='Optional output XML path')
    parser.add_argument('-r', '--root', dest='root', default='root', help='Root element name')
    parser.add_argument('-e', '--element', dest='element', default='item', help='Element name for items')
    parser.add_argument('-x', '--xsd', dest='xsd', help='Optional XSD path to validate against')

    args = parser.parse_args(argv)

    input_path = args.input_file
    if not os.path.exists(input_path):
        print(f'Input file not found: {input_path}')
        sys.exit(2)

    objs = load_json_objects(input_path)
    if not objs:
        print('No JSON objects found in input')
        sys.exit(1)

    xml_str = convert_to_xml(objs, root_name=args.root, item_name=args.element)
    xml_bytes = xml_str.encode('utf-8')

    # Ensure output directory
    if args.output_file:
        out_path = args.output_file
    else:
        base = os.path.splitext(os.path.basename(input_path))[0]
        out_dir = os.path.join(os.getcwd(), 'outputs', 'json_responses')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, base + '.xml')

    with open(out_path, 'wb') as f:
        f.write(xml_bytes)

    print(f'Wrote XML to {out_path}')

    if args.xsd:
        valid, errors = validate_xml(xml_bytes, args.xsd)
        if valid:
            print('XML is valid against XSD')
        else:
            print('XML failed XSD validation:')
            for e in errors:
                print('  ' + e)
            sys.exit(3)


if __name__ == '__main__':
    main()
