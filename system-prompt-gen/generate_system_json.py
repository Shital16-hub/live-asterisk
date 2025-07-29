#!/usr/bin/env python3
"""
generate_system_json.py

Reads a base system prompt from `system_prompt.txt`, parses all `.txt` files
in the `services/` directory for service definitions, injects a formatted
Services & Pricing section into the prompt, and writes out `system.json`.
"""

import os
import json

def parse_service_file(path):
    """
    Parse a service definition file into a dict with keys:
      SERVICE, BASE_PRICE, DESCRIPTION, REQUIREMENTS, TIME, PRICING_RULES (list).
    """
    service = {}
    pricing_rules = []
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith('-'):
                # pricing rule
                pricing_rules.append(line.lstrip('- ').strip())
            else:
                # key: value
                if ':' in line:
                    key, val = line.split(':', 1)
                    service[key.strip()] = val.strip()
    service['PRICING_RULES'] = pricing_rules
    return service

def format_services_md(services):
    """
    Given a list of service dicts, return a markdown string for them.
    """
    lines = []
    for svc in services:
        name = svc.get('SERVICE', 'Unknown Service')
        lines.append(f"- **{name}**")
        if 'BASE_PRICE' in svc:
            lines.append(f"  - Base Price: ${svc['BASE_PRICE']}")
        if 'DESCRIPTION' in svc:
            lines.append(f"  - Description: {svc['DESCRIPTION']}")
        if 'REQUIREMENTS' in svc:
            lines.append(f"  - Requirements: {svc['REQUIREMENTS']}")
        if 'TIME' in svc:
            lines.append(f"  - Estimated Time: {svc['TIME']}")
        if svc.get('PRICING_RULES'):
            lines.append("  - Pricing Rules:")
            for rule in svc['PRICING_RULES']:
                lines.append(f"    - {rule}")
        lines.append("")  # blank line between services
    return "\n".join(lines)

def main():
    base_file = "system_prompt.txt"
    services_dir = "services_docs"
    output_file = "system.json"
    service_area_file = "popular-service-area.txt"

    # 1. Load base prompt
    with open(base_file, 'r', encoding='utf-8') as f:
        base_prompt = f.read()

    # 2. Parse all service files
    service_files = sorted(
        os.path.join(services_dir, fn)
        for fn in os.listdir(services_dir)
        if fn.lower().endswith('.txt')
    )
    services = [parse_service_file(fp) for fp in service_files]

    # 3. Format services section as markdown
    services_md = format_services_md(services)

    # 4. Insert into base prompt at the "6. Services & Pricing Information" header
    marker = "6. Services & Pricing Information"
    idx = base_prompt.find(marker)
    if idx == -1:
        raise RuntimeError(f"Marker '{marker}' not found in {base_file}")
    line_end = base_prompt.find("\n", idx)
    insert_pos = line_end + 1
    merged = (
        base_prompt[:insert_pos]
        + "\n"
        + services_md
        + base_prompt[insert_pos:]
    )

    # 5. Insert service area section after '7. Our Popular Service Area' header
    area_marker = "7. Our Popular Service Area"
    area_idx = merged.find(area_marker)
    if area_idx == -1:
        raise RuntimeError(f"Marker '{area_marker}' not found in {base_file}")
    area_line_end = merged.find("\n", area_idx)
    area_insert_pos = area_line_end + 1
    # Read service area file
    with open(service_area_file, 'r', encoding='utf-8') as f:
        area_content = f.read().strip()
    area_note = "The service areas listed below are popular, but service is available in other areas as well.\n\n"
    merged = (
        merged[:area_insert_pos]
        + area_note
        + area_content
        + "\n"
        + merged[area_insert_pos:]
    )

    # 6. Wrap as JSON and write out
    output = [
        {
            "role": "system",
            "content": merged
        }
    ]
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ Generated {output_file}")

if __name__ == "__main__":
    main()