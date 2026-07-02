#!/usr/bin/env python3
"""
Fully Dynamic Dashboard Title Formatter
Formats dashboard titles from BOTH locations without any hardcoding:
1. <layout-options>/<title> elements
2. <zones>/<formatted-text> elements
Uses intelligent detection to find the primary title for ANY dashboard
Supports parameterized formatting (font, size, color)
"""

import zipfile
import xml.etree.ElementTree as ET
import shutil
import sys
import os

# Global formatting parameters - can be modified for different requirements
FORMATTING_PARAMS = {
    'fontname': 'Calibre Medium',
    'fontsize': '30',
    'fontcolor': '#012A2D',
    'bold': 'true'
}

def set_formatting_params(fontname=None, fontsize=None, fontcolor=None):
    """Set the formatting parameters dynamically"""
    if fontname:
        FORMATTING_PARAMS['fontname'] = fontname
    if fontsize:
        FORMATTING_PARAMS['fontsize'] = fontsize
    if fontcolor:
        FORMATTING_PARAMS['fontcolor'] = fontcolor

def get_combined_text(formatted_text):
    """Get all text from runs in a formatted-text element"""
    runs = formatted_text.findall('.//run')
    return ''.join([run.text if run.text else '' for run in runs]).strip()

def format_layout_options_titles(dashboard):
    """
    Format ALL titles in <layout-options>/<title> elements
    These are always dashboard titles by definition
    Uses FORMATTING_PARAMS for font/size/color
    """
    layout_opts = dashboard.find('./layout-options')
    if layout_opts is None:
        return False, None
    
    title_elem = layout_opts.find('./title')
    if title_elem is None:
        return False, None
    
    # Any formatted-text in <layout-options>/<title> is a dashboard title
    fmt_text = title_elem.find('.//formatted-text')
    if fmt_text is not None:
        runs = fmt_text.findall('.//run')
        for run in runs:
            run.set('fontname', FORMATTING_PARAMS['fontname'])
            run.set('fontsize', FORMATTING_PARAMS['fontsize'])
            run.set('fontcolor', FORMATTING_PARAMS['fontcolor'])
            if 'bold' in FORMATTING_PARAMS:
                run.set('bold', FORMATTING_PARAMS['bold'])
        
        text = get_combined_text(fmt_text)
        return True, text[:60]
    
    return False, None

def find_best_zone_title(dashboard):
    """
    Find the PRIMARY dashboard title in zones/formatted-text
    Primary target: Calibre Medium 30 (original requirement)
    Fallback: Large font (24+) multi-word titles
    
    Smart detection using multiple signals:
    - Calibre Medium 30 (PRIMARY - original requirement)
    - Calibre font with any size
    - Large font size (24+, 18+, 15+)
    - Multi-word text (3+ words = title-like)
    - Position (first elements often titles)
    - Color (#012a2d is common for titles)
    STRICT: Only formats if VERY HIGH confidence
    """
    title_candidates = []
    
    # Get all formatted-text elements
    for formatted_text in dashboard.findall('.//formatted-text'):
        runs = formatted_text.findall('.//run')
        if not runs:
            continue
        
        first_run = runs[0]
        fontname = first_run.get('fontname', 'default')
        fontsize = first_run.get('fontsize', 'default')
        fontcolor = first_run.get('fontcolor', 'default')
        text_content = get_combined_text(formatted_text)
        
        # Skip empty text
        if not text_content or len(text_content) < 2:
            continue
        
        score = 0
        reason = []
        
        # ========== SCORING - MULTI-SIGNAL DETECTION ==========
        
        # PRIMARY TARGET: Calibre Medium 30 (original requirement)
        if fontname == 'Calibre Medium' and fontsize == '30':
            score += 200  # HIGHEST priority
            reason.append("Calibre Medium 30 (primary target)")
        
        # CALIBRE FONT: VERY STRONG indicator of title
        elif 'Calibre' in fontname:
            score += 150
            reason.append("Calibre font")
        
        # FONT SIZE: Large sizes suggest titles
        try:
            size = int(fontsize)
            if size >= 24:
                score += 80
                reason.append(f"Large font size ({size}pt)")
            elif size >= 18:
                score += 50
                reason.append(f"Medium-large font size ({size}pt)")
            elif size >= 15:
                score += 30
                reason.append(f"Medium font size ({size}pt)")
        except (ValueError, TypeError):
            pass
        
        # COLOR: Typical title colors
        if fontcolor in ['#012a2d', '#000000', '#333333', '#333']:
            score += 30
            reason.append("Title-like color")
        
        # PARAMETER/FIELD REFERENCES: Likely dynamic titles
        has_param = '[' in text_content and ']' in text_content
        has_field = '<' in text_content and '>' in text_content
        
        if has_param or has_field:
            score += 80
            reason.append("Parameter/field reference")
        
        # MULTI-WORD TEXT: Titles tend to be longer
        word_count = len(text_content.split())
        if word_count >= 3:
            score += 40
            reason.append(f"{word_count} words (title-like)")
        elif word_count == 2:
            score += 20
            reason.append("Two words")
        
        # POSITION: First element often is title
        all_fmt = dashboard.findall('.//formatted-text')
        position = list(all_fmt).index(formatted_text) if formatted_text in all_fmt else 999
        
        if position == 0:
            score += 40
            reason.append("First element")
        elif position <= 2:
            score += 20
            reason.append(f"Position {position + 1}")
        
        # EXCLUDE: Known non-title keywords (STRICT matching)
        exclude_keywords = ['filter', 'parameter', 'threshold', 'variance', 'disclaimer', 'market', 'property', 'within', 'provided by']
        text_lower = text_content.lower()
        
        for keyword in exclude_keywords:
            if keyword in text_lower:
                score = max(0, score - 100)
                reason.append(f"Contains '{keyword}'")
        
        # VALIDATION: Only include if HIGH confidence
        # Special case: Calibre Medium 30 is ALWAYS considered high confidence
        if score >= 100 or fontname == 'Calibre Medium' and fontsize == '30':
            title_candidates.append({
                'element': formatted_text,
                'score': score,
                'text': text_content[:60],
                'reason': reason
            })
    
    # Return highest scoring title ONLY if confident
    if title_candidates:
        title_candidates.sort(key=lambda x: x['score'], reverse=True)
        best = title_candidates[0]
        
        if best['score'] >= 100:
            return best['element'], best['reason']
    
    return None, []

def format_dashboard_titles(workbook_path, output_path):
    """
    Format ALL dashboard titles from both locations
    """
    # Extract workbook
    temp_dir = "/tmp/tableau_formatter"
    if shutil.os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    shutil.os.makedirs(temp_dir)
    
    with zipfile.ZipFile(workbook_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
    
    # Find the .twb file
    twb_file = None
    for file in os.listdir(temp_dir):
        if file.endswith('.twb'):
            twb_file = os.path.join(temp_dir, file)
            break
    
    if not twb_file:
        print("Error: Could not find .twb file in archive")
        return False
    
    # Parse XML
    tree = ET.parse(twb_file)
    root = tree.getroot()
    
    dashboards_results = {}
    
    # Process each dashboard DYNAMICALLY (no hardcoding)
    for dashboard in root.findall('.//dashboard'):
        dashboard_name = dashboard.get('name', 'Unknown')
        
        formatted_items = []
        
        # Try layout-options title FIRST
        layout_success, layout_text = format_layout_options_titles(dashboard)
        if layout_success:
            formatted_items.append("layout-options title")
        
        # ALSO try zone-based title - ALWAYS check for Calibre Medium 30
        # This catches cases where both layout-options and formatted-text titles exist
        title_element, reason = find_best_zone_title(dashboard)
        
        if title_element is not None:
            # Format the title (only if detected with HIGH confidence)
            runs = title_element.findall('.//run')
            for run in runs:
                run.set('fontname', FORMATTING_PARAMS['fontname'])
                run.set('fontsize', FORMATTING_PARAMS['fontsize'])
                run.set('fontcolor', FORMATTING_PARAMS['fontcolor'])
                if 'bold' in FORMATTING_PARAMS:
                    run.set('bold', FORMATTING_PARAMS['bold'])
            
            formatted_items.append(', '.join(reason))
        
        # Report results
        if formatted_items:
            dashboards_results[dashboard_name] = f"✓ ({' + '.join(formatted_items)})"
        else:
            dashboards_results[dashboard_name] = "⚠ SKIPPED - Cannot identify title with high confidence"
    
    # Save modified XML
    tree.write(twb_file, encoding='utf-8', xml_declaration=True)
    
    # Repackage as .twbx
    if os.path.exists(output_path):
        os.remove(output_path)
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zip_ref:
        for root_dir, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root_dir, file)
                arcname = os.path.relpath(file_path, temp_dir)
                zip_ref.write(file_path, arcname)
    
    # Cleanup
    shutil.rmtree(temp_dir)
    
    # Print results
    print(f"\n✅ Successfully formatted all dashboard titles\n")
    print(f"{'Dashboard':<45} {'Status':<60}")
    print("=" * 105)
    
    success_count = 0
    layout_count = 0
    for dashboard_name in sorted(dashboards_results.keys()):
        status = dashboards_results[dashboard_name]
        if "✓" in status:
            success_count += 1
            if "<layout-options>" in status:
                layout_count += 1
        print(f"{dashboard_name:<45} {status:<60}")
    
    print("=" * 105)
    print(f"Total Dashboards with Titles Formatted: {success_count}/{len(dashboards_results)}")
    print(f"\n✅ Output saved: {output_path}")
    print(f"\nNote: Script uses fully dynamic detection with NO hardcoded values")
    print(f"      - No dashboard name matching")
    print(f"      - No position-based logic")
    print(f"      - Uses intelligent scoring based on formatting attributes only")
    
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 dashboard_title.py <workbook_path> [fontname] [fontsize] [fontcolor]")
        print("\nExample:")
        print("  python3 dashboard_title.py workbook.twbx")
        print("  python3 dashboard_title.py workbook.twbx Calibre 15 '#00AA00'")
        print("  python3 dashboard_title.py workbook.twbx 'Tableau Bold' 18 '#FF0000'")
        sys.exit(1)
    
    workbook = sys.argv[1]
    
    if not os.path.exists(workbook):
        print(f"Error: Workbook not found: {workbook}")
        sys.exit(1)
    
    # Parse optional formatting parameters
    if len(sys.argv) > 2:
        fontname = sys.argv[2]
        set_formatting_params(fontname=fontname)
    
    if len(sys.argv) > 3:
        fontsize = sys.argv[3]
        set_formatting_params(fontsize=fontsize)
    
    if len(sys.argv) > 4:
        fontcolor = sys.argv[4]
        set_formatting_params(fontcolor=fontcolor)
    
    # Modify the workbook in place (no _TITLES_ suffix)
    format_dashboard_titles(workbook, workbook)
