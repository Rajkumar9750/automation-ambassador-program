#!/usr/bin/env python3
"""
Change All Filters to Multiple Values (Dropdown) Mode
Converts all filter types to the 'checkdropdown' mode in Tableau
"""

import zipfile
import os
import re
import argparse
import shutil
from datetime import datetime

def change_to_multiple_dropdown(twbx_path, output_dir=None):
    """Change all filters to Multiple Values (dropdown) mode"""
    
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
    
    print("\n🔄 CHANGING FILTER TYPE TO: Multiple Values (dropdown)")
    print("🔄 ENABLING: Show Apply Button on all filters\n")
    
    # Count filter types before (both single and double quotes)
    # Common modes:
    # - dropdown = Single Value (dropdown)
    # - checkdropdown = Multiple Values (dropdown)
    # - radiolist = Single Value (list)
    # - checklist = Multiple Values (list)
    # - typeinlist = Multiple Values (custom list)
    # - slider = Single Value (slider)
    # - wildcard = Wildcard Match
    
    dropdown_before = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']dropdown["\']|mode=["\']dropdown["\']\s+[^>]*type-v2=["\']filter["\']', content))
    checkdropdown_before = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']checkdropdown["\']|mode=["\']checkdropdown["\']\s+[^>]*type-v2=["\']filter["\']', content))
    radiolist_before = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']radiolist["\']|mode=["\']radiolist["\']\s+[^>]*type-v2=["\']filter["\']', content))
    checklist_before = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']checklist["\']|mode=["\']checklist["\']\s+[^>]*type-v2=["\']filter["\']', content))
    typeinlist_before = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']typeinlist["\']|mode=["\']typeinlist["\']\s+[^>]*type-v2=["\']filter["\']', content))
    slider_before = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']slider["\']|mode=["\']slider["\']\s+[^>]*type-v2=["\']filter["\']', content))
    wildcard_before = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']wildcard["\']|mode=["\']wildcard["\']\s+[^>]*type-v2=["\']filter["\']', content))
    
    total_filters_before = dropdown_before + checkdropdown_before + radiolist_before + checklist_before + typeinlist_before + slider_before + wildcard_before
    
    # Count filters with show-apply attribute
    show_apply_true_before = len(re.findall(r'type-v2=["\']filter["\'][^>]*show-apply=["\']true["\']|show-apply=["\']true["\'][^>]*type-v2=["\']filter["\']', content))
    show_apply_false_before = len(re.findall(r'type-v2=["\']filter["\'][^>]*show-apply=["\']false["\']|show-apply=["\']false["\'][^>]*type-v2=["\']filter["\']', content))
    no_show_apply_before = total_filters_before - show_apply_true_before - show_apply_false_before
    
    print(f"📊 Before modifications:")
    print(f"   • Single Value (dropdown) [mode='dropdown']: {dropdown_before}")
    print(f"   • Multiple Values (dropdown) [mode='checkdropdown']: {checkdropdown_before}")
    print(f"   • Single Value (list) [mode='radiolist']: {radiolist_before}")
    print(f"   • Multiple Values (list) [mode='checklist']: {checklist_before}")
    print(f"   • Multiple Values (custom list) [mode='typeinlist']: {typeinlist_before}")
    print(f"   • Slider mode [mode='slider']: {slider_before}")
    print(f"   • Wildcard mode [mode='wildcard']: {wildcard_before}")
    print(f"   • Total filter zones: {total_filters_before}")
    print(f"\n   Apply Button Status:")
    print(f"   • Filters with Apply button enabled: {show_apply_true_before}")
    print(f"   • Filters with Apply button disabled: {show_apply_false_before}")
    print(f"   • Filters without show-apply attribute: {no_show_apply_before}")
    
    # Change 1: Convert mode="dropdown" to mode="checkdropdown" (Single Value → Multiple Values)
    content = re.sub(
        r'(<zone[^>]*type-v2=["\']filter["\'][^>]*)mode=["\']dropdown["\']',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'"),
        content
    )
    
    # Change 2: Convert mode="radiolist" to mode="checkdropdown" (Single Value list → Multiple Values dropdown)
    content = re.sub(
        r'(<zone[^>]*type-v2=["\']filter["\'][^>]*)mode=["\']radiolist["\']',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'"),
        content
    )
    
    # Change 3: Convert mode="checklist" to mode="checkdropdown" (Multiple Values list → Multiple Values dropdown)
    content = re.sub(
        r'(<zone[^>]*type-v2=["\']filter["\'][^>]*)mode=["\']checklist["\']',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'"),
        content
    )
    
    # Change 4: Convert mode="typeinlist" to mode="checkdropdown" (Multiple Values custom list → Multiple Values dropdown)
    content = re.sub(
        r'(<zone[^>]*type-v2=["\']filter["\'][^>]*)mode=["\']typeinlist["\']',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'"),
        content
    )
    
    # Change 5: Convert mode="slider" to mode="checkdropdown"
    content = re.sub(
        r'(<zone[^>]*type-v2=["\']filter["\'][^>]*)mode=["\']slider["\']',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'"),
        content
    )
    
    # Change 6: Convert mode="wildcard" to mode="checkdropdown"
    content = re.sub(
        r'(<zone[^>]*type-v2=["\']filter["\'][^>]*)mode=["\']wildcard["\']',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'"),
        content
    )
    
    # Also handle reverse order (mode before type-v2)
    content = re.sub(
        r'(<zone[^>]*)mode=["\']dropdown["\']([^>]*type-v2=["\']filter["\'])',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'") + m.group(2),
        content
    )
    
    content = re.sub(
        r'(<zone[^>]*)mode=["\']radiolist["\']([^>]*type-v2=["\']filter["\'])',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'") + m.group(2),
        content
    )
    
    content = re.sub(
        r'(<zone[^>]*)mode=["\']checklist["\']([^>]*type-v2=["\']filter["\'])',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'") + m.group(2),
        content
    )
    
    content = re.sub(
        r'(<zone[^>]*)mode=["\']typeinlist["\']([^>]*type-v2=["\']filter["\'])',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'") + m.group(2),
        content
    )
    
    content = re.sub(
        r'(<zone[^>]*)mode=["\']slider["\']([^>]*type-v2=["\']filter["\'])',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'") + m.group(2),
        content
    )
    
    content = re.sub(
        r'(<zone[^>]*)mode=["\']wildcard["\']([^>]*type-v2=["\']filter["\'])',
        lambda m: m.group(1) + ('mode="checkdropdown"' if 'mode="' in m.group(0) else "mode='checkdropdown'") + m.group(2),
        content
    )
    
    # Change 7: Add show-apply='true' and show-enumeration='true' to filters
    # show-enumeration='true' disables custom list typing, forcing dropdown-only selection
    def add_filter_attributes(match):
        zone_tag = match.group(0)
        quote_style = '"' if 'type-v2="filter"' in zone_tag else "'"
        modified = zone_tag[:-1]  # Remove closing >
        
        # Add show-apply if missing
        if 'show-apply' not in zone_tag:
            modified += f' show-apply={quote_style}true{quote_style}'
        
        # Add show-enumeration if missing (this disables custom list typing)
        if 'show-enumeration' not in zone_tag:
            modified += f' show-enumeration={quote_style}true{quote_style}'
        
        return modified + '>'
    
    content = re.sub(
        r'<zone[^>]*type-v2=["\']filter["\'][^>]*>',
        add_filter_attributes,
        content
    )
    
    # Change 8: Change show-apply='false' to show-apply='true'
    content = re.sub(
        r'(<zone[^>]*type-v2=["\']filter["\'][^>]*)show-apply=["\']false["\']',
        lambda m: m.group(1) + ('show-apply="true"' if 'show-apply="' in m.group(0) else "show-apply='true'"),
        content
    )
    
    # Count after replacement
    dropdown_after = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']dropdown["\']|mode=["\']dropdown["\']\s+[^>]*type-v2=["\']filter["\']', content))
    checkdropdown_after = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']checkdropdown["\']|mode=["\']checkdropdown["\']\s+[^>]*type-v2=["\']filter["\']', content))
    radiolist_after = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']radiolist["\']|mode=["\']radiolist["\']\s+[^>]*type-v2=["\']filter["\']', content))
    checklist_after = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']checklist["\']|mode=["\']checklist["\']\s+[^>]*type-v2=["\']filter["\']', content))
    typeinlist_after = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']typeinlist["\']|mode=["\']typeinlist["\']\s+[^>]*type-v2=["\']filter["\']', content))
    slider_after = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']slider["\']|mode=["\']slider["\']\s+[^>]*type-v2=["\']filter["\']', content))
    wildcard_after = len(re.findall(r'type-v2=["\']filter["\']\s+[^>]*mode=["\']wildcard["\']|mode=["\']wildcard["\']\s+[^>]*type-v2=["\']filter["\']', content))
    
    total_filters_after = dropdown_after + checkdropdown_after + radiolist_after + checklist_after + typeinlist_after + slider_after + wildcard_after
    
    # Count show-apply after
    show_apply_true_after = len(re.findall(r'type-v2=["\']filter["\'][^>]*show-apply=["\']true["\']|show-apply=["\']true["\'][^>]*type-v2=["\']filter["\']', content))
    show_apply_false_after = len(re.findall(r'type-v2=["\']filter["\'][^>]*show-apply=["\']false["\']|show-apply=["\']false["\'][^>]*type-v2=["\']filter["\']', content))
    no_show_apply_after = total_filters_after - show_apply_true_after - show_apply_false_after
    
    print(f"\n📊 After modifications:")
    print(f"   • Single Value (dropdown) [mode='dropdown']: {dropdown_after}")
    print(f"   • Multiple Values (dropdown) [mode='checkdropdown']: {checkdropdown_after}")
    print(f"   • Single Value (list) [mode='radiolist']: {radiolist_after}")
    print(f"   • Multiple Values (list) [mode='checklist']: {checklist_after}")
    print(f"   • Multiple Values (custom list) [mode='typeinlist']: {typeinlist_after}")
    print(f"   • Slider mode [mode='slider']: {slider_after}")
    print(f"   • Wildcard mode [mode='wildcard']: {wildcard_after}")
    print(f"   • Total filter zones: {total_filters_after}")
    print(f"\n   Apply Button Status:")
    print(f"   • Filters with Apply button enabled: {show_apply_true_after}")
    print(f"   • Filters with Apply button disabled: {show_apply_false_after}")
    print(f"   • Filters without show-apply attribute: {no_show_apply_after}")
    
    changes_made = (dropdown_before - dropdown_after + 
                   radiolist_before - radiolist_after +
                   checklist_before - checklist_after +
                   typeinlist_before - typeinlist_after +
                   slider_before - slider_after + 
                   wildcard_before - wildcard_after)
    
    apply_button_changes = (no_show_apply_before - no_show_apply_after + 
                           show_apply_false_before - show_apply_false_after)
    
    print(f"\n✅ FILTER TYPE CONVERSION COMPLETE")
    print(f"   Filters converted to Multiple Values (dropdown): {changes_made}")
    print(f"   Already Multiple Values (dropdown): {checkdropdown_before}")
    print(f"   Total filters now as Multiple Values (dropdown): {checkdropdown_after}")
    print(f"\n✅ APPLY BUTTON ENABLED")
    print(f"   Filters with Apply button enabled: {apply_button_changes}")
    print(f"   Total filters with Apply button: {show_apply_true_after}")
    
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
    print(f"SUCCESS: All filters configured")
    print(f"  • Filter type: Multiple Values (dropdown)")
    print(f"  • Apply button: Enabled on all filters")
    print(f"Total conversions: {changes_made} filter types, {apply_button_changes} apply buttons")
    print(f"="*80)

if __name__ == "__main__":
    print("\n" + "="*80)
    print("TABLEAU FILTER TYPE CONVERTER")
    print("• Change all filters to Multiple Values (dropdown)")
    print("• Enable Apply button on all filters")
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
    
    change_to_multiple_dropdown(twbx_path, output_dir)
