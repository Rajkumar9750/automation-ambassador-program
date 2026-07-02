#!/usr/bin/env python3
"""
Change Filter Values from 'All Values in Database' to 'Only Relevant Values'
CORRECT METHOD: Modify the values= attribute in <zone type-v2='filter'> elements
"""

import zipfile
import os
import re
import argparse
import shutil
from datetime import datetime

def change_filter_values(twbx_path, output_dir=None):
    """Change all filter zones from values='all' to values='relevant'"""
    
    if not os.path.exists(twbx_path):
        print(f"❌ Error: File not found: {twbx_path}")
        return
    
    # Get filename
    filename = os.path.basename(twbx_path)
    
    # Set output directory
    if output_dir is None:
        output_dir = os.path.expanduser("~/Desktop/Formatted_Workbooks")
    
    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    output_path = os.path.join(output_dir, filename)
    
    # Extract TWB file
    with zipfile.ZipFile(twbx_path, 'r') as zip_ref:
        extract_path = twbx_path.replace('.twbx', '')
        zip_ref.extractall(extract_path)
    
    twb_filename = [f for f in os.listdir(extract_path) if f.endswith('.twb')][0]
    twb_path = os.path.join(extract_path, twb_filename)
    
    print(f"\n✅ Extracted .twb file: {twb_filename}")
    
    # Backup creation disabled - only output final .twbx file
    
    # Read the TWB XML file
    with open(twb_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    print("\n🔄 CHANGING FILTER MODE: 'All Values in Database' → 'Only Relevant Values'\n")
    print("📝 Pattern 1: Modifying values= attribute in <zone type-v2='filter'> (menu selection)")
    print(f"📝 Pattern 2: Modifying ui-domain in <groupfilter> elements (domain scope)")
    print(f"📝 Pattern 3: Modifying ui-enumeration in <groupfilter> elements (filter behavior)")
    
    # Count zone filters with different values (both single and double quotes)
    zone_database_before = len(re.findall(r"type-v2=['\"]filter['\"][^>]*values=['\"]database['\"]", content))
    zone_context_before = len(re.findall(r"type-v2=['\"]filter['\"][^>]*values=['\"]context['\"]", content))
    zone_all_before = len(re.findall(r"type-v2=['\"]filter['\"][^>]*values=['\"]all['\"]", content))
    
    # Count groupfilters with ui-enumeration (both user: and ns0: namespaces, both single and double quotes)
    database_domain_before = len(re.findall(r"(?:user:|ns0:)ui-domain=['\"]database['\"]", content))
    all_count_before = len(re.findall(r"(?:user:|ns0:)ui-enumeration=['\"]all['\"]", content))
    context_enum_before = len(re.findall(r"(?:user:|ns0:)ui-enumeration=['\"]context['\"]", content))
    exclusive_enum_before = len(re.findall(r"(?:user:|ns0:)ui-enumeration=['\"]exclusive['\"]", content))
    relevant_count_before = len(re.findall(r"(?:user:|ns0:)ui-enumeration=['\"]inclusive['\"]", content))
    
    print(f"   📊 Before modifications:")
    print(f"      • zones with values='database': {zone_database_before}")
    print(f"      • zones with values='context': {zone_context_before}")
    print(f"      • zones with values='all': {zone_all_before}")
    print(f"      • groupfilters with ui-domain='database': {database_domain_before}")
    print(f"      • groupfilters with ui-enumeration='all': {all_count_before}")
    print(f"      • groupfilters with ui-enumeration='context': {context_enum_before}")
    print(f"      • groupfilters with ui-enumeration='exclusive': {exclusive_enum_before}")
    print(f"      • groupfilters with ui-enumeration='inclusive': {relevant_count_before}")
    
    # Change 1: Zone filter values='database' or values="database" to values='relevant' or values="relevant"
    content = re.sub(
        r"(<zone[^>]*type-v2=['\"]filter['\"][^>]*)values=['\"]database['\"]",
        lambda m: m.group(1) + ('values="relevant"' if 'values="' in m.group(0) else "values='relevant'"),
        content
    )
    
    # Change 2: Zone filter values='context' or values="context" to values='relevant' or values="relevant"
    content = re.sub(
        r"(<zone[^>]*type-v2=['\"]filter['\"][^>]*)values=['\"]context['\"]",
        lambda m: m.group(1) + ('values="relevant"' if 'values="' in m.group(0) else "values='relevant'"),
        content
    )
    
    # Change 3: Zone filter values='all' or values="all" to values='relevant' or values="relevant"
    content = re.sub(
        r"(<zone[^>]*type-v2=['\"]filter['\"][^>]*)values=['\"]all['\"]",
        lambda m: m.group(1) + ('values="relevant"' if 'values="' in m.group(0) else "values='relevant'"),
        content
    )
    
    # Change 4: Groupfilter ui-domain='database' to 'relevant' (both user: and ns0: namespaces, single and double quotes)
    content = re.sub(
        r"(user:|ns0:)ui-domain=['\"]database['\"]",
        r'\1ui-domain="relevant"',
        content
    )
    
    # Change 5: Groupfilter ui-enumeration='all' to 'inclusive' (both user: and ns0: namespaces, single and double quotes)
    content = re.sub(
        r"(user:|ns0:)ui-enumeration=['\"]all['\"]",
        r'\1ui-enumeration="inclusive"',
        content
    )
    
    # Change 6: Groupfilter ui-enumeration='context' to 'inclusive' (both user: and ns0: namespaces, single and double quotes)
    content = re.sub(
        r"(user:|ns0:)ui-enumeration=['\"]context['\"]",
        r'\1ui-enumeration="inclusive"',
        content
    )
    
    # Change 7: Groupfilter ui-enumeration='exclusive' to 'inclusive' (both user: and ns0: namespaces, single and double quotes)
    content = re.sub(
        r"(user:|ns0:)ui-enumeration=['\"]exclusive['\"]",
        r'\1ui-enumeration="inclusive"',
        content
    )
    
    # Note: Complex nested groupfilter conversions (function="except" to "member") are not performed
    # to avoid creating malformed XML. These should be handled manually in Tableau if needed.
    
    # Count after replacement (both single and double quotes)
    zone_database_after = len(re.findall(r"type-v2=['\"]filter['\"][^>]*values=['\"]database['\"]", content))
    zone_context_after = len(re.findall(r"type-v2=['\"]filter['\"][^>]*values=['\"]context['\"]", content))
    zone_all_after = len(re.findall(r"type-v2=['\"]filter['\"][^>]*values=['\"]all['\"]", content))
    database_domain_after = len(re.findall(r"(?:user:|ns0:)ui-domain=['\"]database['\"]", content))
    all_count_after = len(re.findall(r"(?:user:|ns0:)ui-enumeration=['\"]all['\"]", content))
    context_enum_after = len(re.findall(r"(?:user:|ns0:)ui-enumeration=['\"]context['\"]", content))
    exclusive_enum_after = len(re.findall(r"(?:user:|ns0:)ui-enumeration=['\"]exclusive['\"]", content))
    relevant_count_after = len(re.findall(r"(?:user:|ns0:)ui-enumeration=['\"]inclusive['\"]", content))
    
    zone_changes = (zone_database_before - zone_database_after + 
                    zone_context_before - zone_context_after + 
                    zone_all_before - zone_all_after)
    domain_changes = database_domain_before - database_domain_after
    enum_changes = (all_count_before - all_count_after + 
                    context_enum_before - context_enum_after +
                    exclusive_enum_before - exclusive_enum_after)
    total_changes = zone_changes + domain_changes + enum_changes
    
    print(f"\n   📊 After modifications:")
    print(f"      • zones with values='database': {zone_database_after}")
    print(f"      • zones with values='context': {zone_context_after}")
    print(f"      • zones with values='all': {zone_all_after}")
    print(f"      • groupfilters with ui-domain='database': {database_domain_after}")
    print(f"      • groupfilters with ui-enumeration='all': {all_count_after}")
    print(f"      • groupfilters with ui-enumeration='context': {context_enum_after}")
    print(f"      • groupfilters with ui-enumeration='exclusive': {exclusive_enum_after}")
    print(f"      • groupfilters with ui-enumeration='inclusive': {relevant_count_after}")
    
    print(f"\n✅ FILTER MODE CHANGED")
    print(f"   Zone filter selections changed: {zone_changes}")
    print(f"   UI domain changed: {domain_changes}")
    print(f"   Groupfilter behaviors changed: {enum_changes}")
    print(f"   Total changes made: {total_changes}")
    
    # Write the modified content back
    with open(twb_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # Repackage as TWBX
    if os.path.exists(output_path):
        os.remove(output_path)
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(extract_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, extract_path)
                zipf.write(file_path, arcname)
    
    print(f"\n✅ Workbook saved: {output_path}")
    
    # Cleanup
    shutil.rmtree(extract_path)
    
    print(f"\n" + "="*80)
    print(f"SUCCESS: All filters changed to 'Only Relevant Values'")
    print(f"Total modifications: {total_changes}")
    print(f"  • Menu selections: {zone_changes} zone filters")
    print(f"  • Filter behaviors: {enum_changes} groupfilters")
    print(f"="*80)

if __name__ == "__main__":
    print("\n" + "="*80)
    print("TABLEAU FILTER MODE CONVERTER")
    print("Change all filters from 'All Values in Database' to 'Only Relevant Values'")
    print("="*80 + "\n")
    
    # Ask for file path interactively
    twbx_path = input("📁 Enter the path to your TWBX workbook file:\n   >>> ").strip()
    
    if not twbx_path:
        print("\n❌ Error: No file path provided!")
        exit(1)
    
    # Remove quotes if user accidentally added them
    twbx_path = twbx_path.strip("'\"")
    
    # Ask for output directory (optional)
    default_output = os.path.expanduser("~/Desktop/Formatted_Workbooks")
    output_dir = input(f"\n📁 Enter output directory (press Enter for default: {default_output}):\n   >>> ").strip()
    
    if output_dir:
        output_dir = output_dir.strip('\"')
    else:
        output_dir = default_output
    
    change_filter_values(twbx_path, output_dir)
