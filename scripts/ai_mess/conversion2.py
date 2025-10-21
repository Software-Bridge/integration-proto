#!/usr/bin/env python3
"""
conversion2.py

Convert a JSON dictionary (fprime topology/dictionary) into AMPCS XML dictionaries
for commands, telemetryChannels, and events. Writes one XML per type.

This script focuses on the blocks you specified:
- 'commands' -> CommandDictionary (RNC path: /Users/gameraman/dev/ampcs-dict-schemas/CommandDictionary.rnc)
- 'telemetryChannels' -> ChannelDictionary (RNC path: /Users/gameraman/dev/ampcs-dict-schemas/ChannelDictionary.rnc)

The script does not perform RELAX NG Compact validation out-of-the-box; it writes XML
that follows a straightforward mapping of fields to elements. If you want strict validation
against the RNC files we can add an RNC->RNG conversion step and validate with lxml.

Usage:
  python3 scripts/ai_mess/conversion2.py -i <input.json> -o outputs/cdict

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
import xml.etree.ElementTree as ET


DEFAULT_COMMAND_RNC = '/Users/gameraman/dev/ampcs-dict-schemas/CommandDictionary.rnc'
DEFAULT_CHANNEL_RNC = '/Users/gameraman/dev/ampcs-dict-schemas/ChannelDictionary.rnc'
DEFAULT_MISSION_NAME = 'Banana Nation'
DEFAULT_SPACECRAFT_IDS = [62]


def clean_value(s):
    """Module-level cleaning: remove control chars and collapse whitespace into single spaces."""
    if s is None:
        return None
    t = str(s)
    t = re.sub(r'[\x00-\x1F]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t if t else None


def load_json(path):
    with open(path, 'r') as f:
        txt = f.read().strip()
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        out = []
        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


def find_block(d, block_names):
    """Search for block in dict using several possible keys."""
    if isinstance(d, dict):
        for name in block_names:
            if name in d:
                return d[name]
        # search case-insensitively
        lk = {k.lower(): k for k in d.keys()}
        for name in block_names:
            if name.lower() in lk:
                return d[lk[name.lower()]]
    return None


def clean_tag(name):
    if not name:
        return 'field'
    s = re.sub(r'[^0-9A-Za-z_\-]', '_', str(name))
    if re.match(r'^[0-9\-]', s):
        s = '_' + s
    return s


def _format_opcode(val):
    if val is None:
        return '0xFFFF'
    try:
        if isinstance(val, str):
            # already formatted
            return val
        return hex(int(val))
    except Exception:
        return str(val)


def gather_args_from_command(cmd):
    """Return a flat list of argument dicts for a command from multiple possible keys, including formalParams."""
    out = []
    for key in ('arguments', 'args', 'parameters', 'formalParams', 'formal_params', 'formalparams'):
        v = cmd.get(key)
        if not v:
            continue
        # if a dict wrapper, try common nested names
        if isinstance(v, dict):
            for nested in ('elements', 'params', 'parameters', 'formalParams', 'items'):
                if nested in v and v[nested]:
                    vv = v[nested]
                    break
            else:
                # treat dict as single arg if it looks like one (has name/type)
                if 'name' in v or 'type' in v or 'argName' in v:
                    out.append(v)
                continue
        else:
            vv = v

        if isinstance(vv, list):
            out.extend(vv)
        else:
            out.append(vv)
    return out


def _add_argument_element(parent, arg):
    """Add an argument element under parent from an argument dict."""
    # name may be nested
    raw_name = arg.get('name') or arg.get('argName') or arg.get('id') or 'arg'
    if isinstance(raw_name, dict):
        name = raw_name.get('name') or raw_name.get('value') or str(raw_name)
    else:
        name = str(raw_name)

    # type/kind may be dict or string
    typ_raw = arg.get('type') or arg.get('kind') or ''
    if isinstance(typ_raw, dict):
        typ = str(typ_raw.get('name') or typ_raw.get('type') or '')
    else:
        typ = str(typ_raw)
    typ = typ.lower()

    bit_length = arg.get('bit_length') or arg.get('bitLength') or arg.get('size')
    # if bit_length is a dict, try common keys
    if isinstance(bit_length, dict):
        bit_length = bit_length.get('value') or bit_length.get('bits') or bit_length.get('size')

    units = arg.get('units') or arg.get('unit') or arg.get('enum_name') or arg.get('cts_item_type')
    if isinstance(units, dict):
        units = units.get('name') or units.get('value') or str(units)

    # choose tag
    if 'unsigned' in typ or typ == 'u32' or typ.startswith('u'):
        tag = 'unsigned_arg'
    elif 'enum' in typ or 'enumer' in typ:
        tag = 'enum_arg'
    elif 'string' in typ or 'var_string' in typ or 'char' in typ:
        tag = 'var_string_arg'
    elif 'repeat' in typ or 'repeat' in name.lower():
        tag = 'repeat_arg'
    else:
        tag = 'unsigned_arg'

    attrs = {'name': name}
    if bit_length is not None:
        attrs['bit_length'] = str(bit_length)
    if units:
        attrs['units'] = str(units)

    # support both lxml and xml.etree.ElementTree parents
    if etree is not None and isinstance(parent, etree._Element):
        el = etree.SubElement(parent, tag, **attrs)
        # description
        desc = arg.get('description') or arg.get('annotation')
        if desc:
            d = etree.SubElement(el, 'description')
            d.text = str(desc)
        # range
        mn = arg.get('min') or (arg.get('range') and arg['range'].get('min'))
        mx = arg.get('max') or (arg.get('range') and arg['range'].get('max'))
        if mn is not None or mx is not None:
            rov = etree.SubElement(el, 'range_of_values')
            inc = etree.SubElement(rov, 'include')
            if mn is not None:
                inc.set('min', str(mn))
            if mx is not None:
                inc.set('max', str(mx))
        return el

    try:
        # xml.etree.ElementTree
        if isinstance(parent, ET.Element):
            el = ET.SubElement(parent, tag)
            for k, v in attrs.items():
                el.set(k, v)
            desc = arg.get('description') or arg.get('annotation')
            if desc:
                d = ET.SubElement(el, 'description')
                d.text = str(desc)
            mn = arg.get('min') or (arg.get('range') and arg['range'].get('min'))
            mx = arg.get('max') or (arg.get('range') and arg['range'].get('max'))
            if mn is not None or mx is not None:
                rov = ET.SubElement(el, 'range_of_values')
                inc = ET.SubElement(rov, 'include')
                if mn is not None:
                    inc.set('min', str(mn))
                if mx is not None:
                    inc.set('max', str(mx))
            return el
    except Exception:
        pass

    # fallback string builder
    parts = [f'<{tag} name="{name}"']
    if bit_length is not None:
        parts.append(f' bit_length="{bit_length}"')
    if units:
        parts.append(f' units="{units}"')
    parts.append('>')
    desc = arg.get('description') or arg.get('annotation')
    if desc:
        parts.append(f'<description>{desc}</description>')
    mn = arg.get('min') or (arg.get('range') and arg['range'].get('min'))
    mx = arg.get('max') or (arg.get('range') and arg['range'].get('max'))
    if mn is not None or mx is not None:
        parts.append('<range_of_values>')
        parts.append(f'<include min="{mn}" max="{mx}"/>')
        parts.append('</range_of_values>')
    parts.append(f'</{tag}>')
    return ''.join(parts)


def build_command_dictionary(data, commands):
    """Build a command_dictionary element/string from commands list and metadata."""
    metadata = data.get('metadata', {}) if isinstance(data, dict) else {}
    # Default mission name overridden to match example
    mission = metadata.get('deploymentName') or metadata.get('mission_name') or metadata.get('mission') or DEFAULT_MISSION_NAME
    version = metadata.get('dictionarySpecVersion') or metadata.get('projectVersion') or '1.0'

    if etree is not None:
        root = etree.Element('command_dictionary')
        header = etree.SubElement(root, 'header', mission_name=str(mission), version=str(version), schema_version='1.0')
        # optional spacecraft ids
        sc_ids = metadata.get('spacecraft_ids') or metadata.get('spacecraftIds') or DEFAULT_SPACECRAFT_IDS
        # always include spacecraft_ids (use default if missing)
        scs = etree.SubElement(header, 'spacecraft_ids')
        for val in ensure_list(sc_ids):
            etree.SubElement(scs, 'spacecraft_id', value=str(val))

        # command_definitions
        defs = etree.SubElement(root, 'command_definitions')
        for cmd in ensure_list(commands):
            opcode = _format_opcode(cmd.get('opcode') or cmd.get('op_code') or cmd.get('id') or cmd.get('value'))
            stem = cmd.get('stem') or cmd.get('name') or cmd.get('qualifiedName') or ''
            class_ = cmd.get('class') or 'FSW'
            fsw = etree.SubElement(defs, 'fsw_command', opcode=str(opcode), stem=str(stem), **{'class':str(class_)})
            # arguments (support formalParams and multiple key variants)
            args = gather_args_from_command(cmd)
            if args:
                a_el = etree.SubElement(fsw, 'arguments')
                for a in args:
                    _add_argument_element(a_el, a)
            # categories
            cats = cmd.get('categories') or cmd.get('category')
            if cats:
                c_el = etree.SubElement(fsw, 'categories')
                if isinstance(cats, dict):
                    for k, v in cats.items():
                        sub = etree.SubElement(c_el, clean_tag(k))
                        sub.text = str(v)
                else:
                    for v in ensure_list(cats):
                        sub = etree.SubElement(c_el, 'module')
                        sub.text = str(v)
            # description / completion
            desc = cmd.get('description') or cmd.get('annotation')
            if desc:
                d = etree.SubElement(fsw, 'description')
                d.text = str(desc)
            comp = cmd.get('completion')
            if comp:
                c = etree.SubElement(fsw, 'completion')
                c.text = str(comp)
        return root
    # fallback build using ElementTree elements for consistent serialization
    root = ET.Element('command_dictionary')
    header = ET.SubElement(root, 'header')
    header.set('mission_name', clean_value(mission) or '')
    header.set('version', clean_value(version) or '')
    header.set('schema_version', '1.0')

    sc_ids = metadata.get('spacecraft_ids') or metadata.get('spacecraftIds') or DEFAULT_SPACECRAFT_IDS
    scs = ET.SubElement(header, 'spacecraft_ids')
    for val in ensure_list(sc_ids):
        sc = ET.SubElement(scs, 'spacecraft_id')
        sc.set('value', str(val))

    defs = ET.SubElement(root, 'command_definitions')
    for cmd in ensure_list(commands):
        opcode = _format_opcode(cmd.get('opcode') or cmd.get('op_code') or cmd.get('id') or cmd.get('value'))
        stem = cmd.get('stem') or cmd.get('name') or cmd.get('qualifiedName') or ''
        class_ = cmd.get('class') or 'FSW'
        fsw = ET.SubElement(defs, 'fsw_command')
        fsw.set('opcode', clean_value(opcode) or '')
        fsw.set('stem', clean_value(stem) or '')
        fsw.set('class', clean_value(class_) or '')

        args = gather_args_from_command(cmd)
        if args:
            a_el = ET.SubElement(fsw, 'arguments')
            for a in args:
                _add_argument_element(a_el, a)

        cats = cmd.get('categories') or cmd.get('category')
        if cats:
            c_el = ET.SubElement(fsw, 'categories')
            if isinstance(cats, dict):
                for k, v in cats.items():
                    sub = ET.SubElement(c_el, clean_tag(k))
                    sub.text = clean_value(v)
            else:
                for v in ensure_list(cats):
                    sub = ET.SubElement(c_el, 'module')
                    sub.text = clean_value(v)

        desc = cmd.get('description') or cmd.get('annotation')
        if desc:
            d = ET.SubElement(fsw, 'description')
            d.text = clean_value(desc)
        comp = cmd.get('completion')
        if comp:
            c = ET.SubElement(fsw, 'completion')
            c.text = clean_value(comp)
    return root


def build_channel_dictionary(data, channels):
    metadata = data.get('metadata', {}) if isinstance(data, dict) else {}
    mission = metadata.get('deploymentName') or 'Unknown'
    version = metadata.get('dictionarySpecVersion') or '1.0'

    if etree is not None:
        root = etree.Element('channel_dictionary')
        header = etree.SubElement(root, 'header', mission_name=str(mission), version=str(version), schema_version='1.0')
        defs = etree.SubElement(root, 'channel_definitions')
        for ch in ensure_list(channels):
            name = ch.get('name') or ch.get('stem') or ch.get('qualifiedName') or ''
            cid = str(ch.get('id') or ch.get('cid') or ch.get('channelId') or '')
            ch_el = etree.SubElement(defs, 'channel', name=str(name))
            if cid:
                ch_el.set('id', cid)
            fmt = ch.get('format') or ch.get('formatSpec')
            if fmt:
                ch_el.set('format', str(fmt))
            units = ch.get('units')
            if units:
                ch_el.set('units', str(units))
            desc = ch.get('description') or ch.get('annotation') or ch.get('display_text')
            if desc:
                d = etree.SubElement(ch_el, 'description')
                d.text = str(desc)
        return root

    # fallback build using ElementTree
    root = ET.Element('channel_dictionary')
    header = ET.SubElement(root, 'header')
    header.set('mission_name', clean_value(mission) or '')
    header.set('version', clean_value(version) or '')
    header.set('schema_version', '1.0')
    defs = ET.SubElement(root, 'channel_definitions')
    for ch in ensure_list(channels):
        name = ch.get('name') or ch.get('stem') or ch.get('qualifiedName') or ''
        cid = ch.get('id') or ch.get('cid') or ch.get('channelId') or ''
        fmt = ch.get('format') or ch.get('formatSpec')
        units = ch.get('units')
        ch_el = ET.SubElement(defs, 'channel')
        ch_el.set('name', clean_value(name) or '')
        if cid:
            ch_el.set('id', clean_value(cid))
        if fmt:
            ch_el.set('format', clean_value(fmt))
        if units:
            ch_el.set('units', clean_value(units))
        desc = ch.get('description') or ch.get('annotation') or ch.get('display_text')
        if desc:
            d = ET.SubElement(ch_el, 'description')
            d.text = clean_value(desc)
    return root


def build_evr_dictionary(data, evrs):
    metadata = data.get('metadata', {}) if isinstance(data, dict) else {}
    mission = metadata.get('deploymentName') or 'Unknown'
    version = metadata.get('dictionarySpecVersion') or '1.0'

    if etree is not None:
        root = etree.Element('evr_dictionary')
        header = etree.SubElement(root, 'header', mission_name=str(mission), version=str(version), schema_version='1.0')
        defs = etree.SubElement(root, 'evr_definitions')
        for e in ensure_list(evrs):
            name = e.get('name') or e.get('stem') or ''
            ev_el = etree.SubElement(defs, 'evr', name=str(name))
            code = e.get('code') or e.get('id')
            if code is not None:
                ev_el.set('code', str(code))
            desc = e.get('description') or e.get('annotation') or e.get('message')
            if desc:
                d = etree.SubElement(ev_el, 'description')
                d.text = str(desc)
        return root

    root = ET.Element('evr_dictionary')
    header = ET.SubElement(root, 'header')
    header.set('mission_name', clean_value(mission) or '')
    header.set('version', clean_value(version) or '')
    header.set('schema_version', '1.0')
    defs = ET.SubElement(root, 'evr_definitions')
    for e in ensure_list(evrs):
        name = e.get('name') or e.get('stem') or ''
        code = e.get('code') or e.get('id') or ''
        ev_el = ET.SubElement(defs, 'evr')
        ev_el.set('name', clean_value(name) or '')
        if code:
            ev_el.set('code', clean_value(code))
        desc = e.get('description') or e.get('annotation') or e.get('message')
        if desc:
            d = ET.SubElement(ev_el, 'description')
            d.text = clean_value(desc)
    return root


def build_xml_from_entries(root_name, item_name, entries):
    """Return lxml element or string XML if lxml not available."""
    if etree is not None:
        root = etree.Element(root_name)
        for e in entries:
            item = etree.SubElement(root, item_name)
            if isinstance(e, dict):
                for k, v in e.items():
                    tag = clean_tag(k)
                    if isinstance(v, dict):
                        parent = etree.SubElement(item, tag)
                        for kk, vv in v.items():
                            ch = etree.SubElement(parent, clean_tag(kk))
                            ch.text = str(vv)
                    elif isinstance(v, list):
                        parent = etree.SubElement(item, tag)
                        for vv in v:
                            ch = etree.SubElement(parent, 'item')
                            ch.text = str(vv)
                    else:
                        ch = etree.SubElement(item, tag)
                        ch.text = str(v)
            else:
                item.text = str(e)
        return root

    # fallback string builder
    def esc(s):
        return (str(s)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))

    parts = ['<?xml version="1.0" encoding="UTF-8"?>', f'<{root_name}>']
    for e in entries:
        parts.append(f'<{item_name}>')
        if isinstance(e, dict):
            for k, v in e.items():
                tag = clean_tag(k)
                if isinstance(v, dict):
                    parts.append(f'<{tag}>')
                    for kk, vv in v.items():
                        parts.append(f'<{clean_tag(kk)}>{esc(vv)}</{clean_tag(kk)}>')
                    parts.append(f'</{tag}>')
                elif isinstance(v, list):
                    parts.append(f'<{tag}>')
                    for vv in v:
                        parts.append(f'<item>{esc(vv)}</item>')
                    parts.append(f'</{tag}>')
                else:
                    parts.append(f'<{tag}>{esc(v)}</{tag}>')
        else:
            parts.append(esc(e))
        parts.append(f'</{item_name}>')
    parts.append(f'</{root_name}>')
    return '\n'.join(parts)


def write_xml(obj, path):
    def _clean_text(s):
        if s is None:
            return None
        # Convert to string and remove ALL control characters (including tabs/newlines)
        t = str(s)
        # remove ASCII control chars (0x00-0x1F) completely
        t = re.sub(r'[\x00-\x1F]', ' ', t)
        # collapse runs of whitespace to a single space
        t = re.sub(r'\s+', ' ', t)
        t = t.strip()
        return t if t else None

    xml_str = None
    if etree is not None and isinstance(obj, etree._Element):
        # clean attributes and text nodes in-place to avoid wrapped text
        for el in obj.iter():
            # attributes: remove control chars and collapse whitespace; keep attribute but set to empty string if none
            for k, v in list(el.attrib.items()):
                cleaned = _clean_text(v)
                el.attrib[k] = cleaned if cleaned is not None else ''
            # element text and tail: set to cleaned string or None (so serializer won't emit blank lines)
            el_text = _clean_text(el.text)
            el_tail = _clean_text(el.tail)
            el.text = el_text
            el.tail = None

    # Custom serializer: produce compact/minified XML (no newlines/indentation)
        def _escape_text(s):
            if s is None:
                return ''
            ss = str(s)
            ss = ss.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # only single-line text now (cleaned earlier); ensure no control chars remain
            ss = re.sub(r'[\x00-\x1F]+', ' ', ss)
            ss = re.sub(r'\s+', ' ', ss).strip()
            return ss

        def _serialize_compact(elem):
            tag = elem.tag
            # attributes (sanitize and escape)
            attrs = ''
            for k, v in elem.attrib.items():
                vv = (v or '')
                vv = re.sub(r'\s+', ' ', vv).strip()
                vv = vv.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
                attrs += f' {k}="{vv}"'

            children = list(elem)
            text = elem.text if elem.text is not None else ''
            text = text.strip() if text else ''

            if not children and not text:
                return f'<{tag}{attrs}/>'
            if not children:
                return f'<{tag}{attrs}>{_escape_text(text)}</{tag}>'

            # element with children: concatenate child serializations directly
            inner = ''
            if text:
                inner += _escape_text(text)
            for c in children:
                inner += _serialize_compact(c)
            return f'<{tag}{attrs}>{inner}</{tag}>'

        # produce compact-but-readable output: one element per line, single-tab indentation for children
        def _serialize_readable(elem, level=0):
            indent = '\t' * level
            tag = elem.tag
            attrs = ''
            for k, v in elem.attrib.items():
                vv = (v or '')
                vv = re.sub(r'\s+', ' ', vv).strip()
                vv = vv.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
                attrs += f' {k}="{vv}"'

            children = list(elem)
            text = elem.text if elem.text is not None else ''
            text = text.strip() if text else ''

            if not children and not text:
                return f'{indent}<{tag}{attrs}/>'
            if not children:
                return f'{indent}<{tag}{attrs}>{_escape_text(text)}</{tag}>'

            lines = [f'{indent}<{tag}{attrs}>']
            if text:
                lines.append(f'{indent}\t{_escape_text(text)}')
            for c in children:
                lines.append(_serialize_readable(c, level+1))
            lines.append(f'{indent}</{tag}>')
            return '\n'.join(lines)

        body = _serialize_readable(obj, level=0)
        out = '<?xml version="1.0" encoding="UTF-8"?>\n' + body
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)
        return

    # Non-lxml fallback (string input or ElementTree.Element)
    # define ET serializer for readable output
    def _escape_text(s):
        if s is None:
            return ''
        ss = str(s)
        ss = ss.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        ss = re.sub(r'[\x00-\x1F]+', ' ', ss)
        ss = re.sub(r'\s+', ' ', ss).strip()
        return ss

    def _serialize_etree(elem, level=0):
        indent = '\t' * level
        tag = elem.tag
        attrs = ''
        for k, v in elem.attrib.items():
            vv = (v or '')
            vv = re.sub(r'\s+', ' ', vv).strip()
            vv = vv.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
            attrs += f' {k}="{vv}"'

        children = list(elem)
        text = elem.text if elem.text is not None else ''
        text = text.strip() if text else ''

        if not children and not text:
            return f'{indent}<{tag}{attrs}/>'
        if not children:
            return f'{indent}<{tag}{attrs}>{_escape_text(text)}</{tag}>'

        lines = [f'{indent}<{tag}{attrs}>']
        if text:
            lines.append(f'{indent}\t{_escape_text(text)}')
        for c in children:
            lines.append(_serialize_etree(c, level+1))
        lines.append(f'{indent}</{tag}>')
        return '\n'.join(lines)

    # If caller passed an ElementTree element, serialize directly
    if isinstance(obj, ET.Element):
        body = _serialize_etree(obj, level=0)
        out = '<?xml version="1.0" encoding="UTF-8"?>\n' + body
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)
        return

    xml_str = str(obj)
    # Try to parse with ElementTree and use our readable serializer to avoid minidom attribute-wrapping issues
    try:
        root = ET.fromstring(xml_str)
        body = _serialize_etree(root, level=0)
        out = '<?xml version="1.0" encoding="UTF-8"?>\n' + body
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)
        return
    except Exception:
        # final fallback: insert single newline between tags for readability
        out = re.sub(r'>\s*<', '>\n<', xml_str)
        out = re.sub(r'\n\s*\n+', '\n', out)
        if not out.lstrip().startswith('<?xml'):
            out = '<?xml version="1.0" encoding="UTF-8"?>\n' + out
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Convert JSON dictionary to AMPCS XML dictionaries (commands, telemetryChannels, events)')
    parser.add_argument('-i', '--input', required=True, help='Input JSON dict file')
    parser.add_argument('-o', '--outdir', default=os.path.join('outputs', 'cdict'), help='Output directory')
    parser.add_argument('--command-rnc', default=DEFAULT_COMMAND_RNC, help='Path to CommandDictionary.rnc (informational)')
    parser.add_argument('--channel-rnc', default=DEFAULT_CHANNEL_RNC, help='Path to ChannelDictionary.rnc (informational)')
    args = parser.parse_args(argv)

    data = load_json(args.input)
    if data is None:
        print('No JSON found in', args.input); sys.exit(1)

    # locate blocks
    commands = find_block(data, ['commands', 'command', 'Commands']) or []
    telemetry = find_block(data, ['telemetryChannels', 'telemetry', 'channels', 'TelemetryChannels']) or []
    events = find_block(data, ['events', 'evrs', 'Evr']) or []

    os.makedirs(args.outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.input))[0]

    written = []
    if commands:
        obj = build_command_dictionary(data, ensure_list(commands))
        p = os.path.join(args.outdir, f'command_{base}.xml')
        write_xml(obj, p); written.append(p)

    if telemetry:
        obj = build_channel_dictionary(data, ensure_list(telemetry))
        p = os.path.join(args.outdir, f'channel_{base}.xml')
        write_xml(obj, p); written.append(p)

    if events:
        obj = build_evr_dictionary(data, ensure_list(events))
        p = os.path.join(args.outdir, f'evr_{base}.xml')
        write_xml(obj, p); written.append(p)

    if written:
        print('Wrote:')
        for w in written:
            print('  ' + w)
    else:
        print('No commands/telemetryChannels/events found in input')


def ensure_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


if __name__ == '__main__':
    main()
