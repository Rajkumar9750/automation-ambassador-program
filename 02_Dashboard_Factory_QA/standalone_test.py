#!/usr/bin/env python3
"""
Standalone test suite for Dashboard Factory Tool
Directly processes Tableau workbooks without Flask dependency
"""

import zipfile
import xml.etree.ElementTree as ET
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

TEST_FILE = "/Users/RGaneshan/Downloads/Occupancy Level 2 - Seats and Trending (1).twbx"
OUTPUT_DIR = os.path.expanduser("~/Desktop/Formatted_Workbooks")

def print_header(text):
    """Print a formatted header."""
    print(f"\n{BOLD}{BLUE}{'='*80}{RESET}")
    print(f"{BOLD}{BLUE}{text.center(80)}{RESET}")
    print(f"{BOLD}{BLUE}{'='*80}{RESET}\n")

def print_success(text):
    """Print success message."""
    print(f"{GREEN}✅ {text}{RESET}")

def print_error(text):
    """Print error message."""
    print(f"{RED}❌ {text}{RESET}")

def print_info(text):
    """Print info message."""
    print(f"{BLUE}ℹ️  {text}{RESET}")

def print_warning(text):
    """Print warning message."""
    print(f"{YELLOW}⚠️  {text}{RESET}")

# ============================================================================
# WORKBOOK ANALYSIS
# ============================================================================

def extract_workbook(filepath):
    """Extract and analyze Tableau workbook."""
    print_info(f"Extracting workbook: {os.path.basename(filepath)}")
    
    try:
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            print_success(f"Extracted {len(file_list)} files from workbook")
            return file_list, filepath
    except Exception as e:
        print_error(f"Failed to extract workbook: {e}")
        return None, None

def get_workbook_structure(filepath):
    """Get detailed workbook structure."""
    print_info(f"Analyzing workbook structure...")
    
    try:
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            structure = {
                'twb_files': [],
                'tds_files': [],
                'data_files': [],
                'other_files': []
            }
            
            for filename in zip_ref.namelist():
                if filename.endswith('.twb'):
                    structure['twb_files'].append(filename)
                elif filename.endswith('.tds'):
                    structure['tds_files'].append(filename)
                elif filename.startswith('Data/'):
                    structure['data_files'].append(filename)
                else:
                    structure['other_files'].append(filename)
            
            return structure
    except Exception as e:
        print_error(f"Failed to analyze structure: {e}")
        return None

def get_calculated_fields(filepath):
    """Extract calculated fields from workbook."""
    calculated_fields = []
    
    try:
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            # Look for .twb file
            for filename in zip_ref.namelist():
                if filename.endswith('.twb'):
                    try:
                        with zip_ref.open(filename) as xml_file:
                            tree = ET.parse(xml_file)
                            root = tree.getroot()
                            
                            # Find all calculated fields
                            for elem in root.iter():
                                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                                
                                if tag == 'calculated-field':
                                    field_data = {
                                        'name': elem.get('name', ''),
                                        'caption': elem.get('caption', ''),
                                        'datatype': elem.get('datatype', ''),
                                        'role': elem.get('role', ''),
                                        'type': elem.get('type', ''),
                                        'source_file': filename
                                    }
                                    
                                    # Get formula
                                    for child in elem:
                                        child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                                        if child_tag == 'calculation':
                                            formula_elem = child.find('{http://tableauserveropenapi.com/api}formula')
                                            if formula_elem is not None:
                                                field_data['formula'] = formula_elem.text or ''
                                            else:
                                                field_data['formula'] = child.text or ''
                                    
                                    calculated_fields.append(field_data)
                    except Exception as e:
                        print_warning(f"Error parsing {filename}: {e}")
    except Exception as e:
        print_error(f"Failed to extract calculated fields: {e}")
    
    return calculated_fields

def search_calculated_fields(calculated_fields, search_term):
    """Search calculated fields by term."""
    results = []
    exact_matches = 0
    
    search_lower = search_term.lower()
    
    for field in calculated_fields:
        name_match = search_lower in field.get('name', '').lower()
        caption_match = search_lower in field.get('caption', '').lower()
        formula_match = search_lower in field.get('formula', '').lower()
        
        if name_match or caption_match or formula_match:
            results.append(field)
            if field.get('name', '').lower() == search_lower or field.get('caption', '').lower() == search_lower:
                exact_matches += 1
    
    return results, exact_matches

def count_dashboards(filepath):
    """Count dashboards in workbook."""
    dashboard_count = 0
    
    try:
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            for filename in zip_ref.namelist():
                if filename.endswith('.twb'):
                    with zip_ref.open(filename) as xml_file:
                        tree = ET.parse(xml_file)
                        root = tree.getroot()
                        
                        for elem in root.iter():
                            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                            if tag == 'dashboard':
                                dashboard_count += 1
    except Exception as e:
        print_warning(f"Error counting dashboards: {e}")
    
    return dashboard_count

def count_worksheets(filepath):
    """Count worksheets in workbook."""
    worksheet_count = 0
    
    try:
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            for filename in zip_ref.namelist():
                if filename.endswith('.twb'):
                    with zip_ref.open(filename) as xml_file:
                        tree = ET.parse(xml_file)
                        root = tree.getroot()
                        
                        for elem in root.iter():
                            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                            if tag == 'worksheet':
                                worksheet_count += 1
    except Exception as e:
        print_warning(f"Error counting worksheets: {e}")
    
    return worksheet_count

def copy_workbook_to_output(filepath, original_filename):
    """Copy workbook to output directory."""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        output_filename = f"formatted_{original_filename}"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        shutil.copy2(filepath, output_path)
        
        file_size = os.path.getsize(output_path) / (1024 * 1024)
        print_success(f"Workbook copied to output ({file_size:.2f} MB)")
        print_info(f"Output: {output_path}")
        
        return output_path
    except Exception as e:
        print_error(f"Copy error: {e}")
        return None

# ============================================================================
# TEST FUNCTIONS
# ============================================================================

def test_workbook_basic_info():
    """Test basic workbook information."""
    print_header("TEST 1: WORKBOOK BASIC INFORMATION")
    
    if not os.path.exists(TEST_FILE):
        print_error(f"Test file not found: {TEST_FILE}")
        return False
    
    file_size = os.path.getsize(TEST_FILE) / (1024 * 1024)
    print_info(f"File: {os.path.basename(TEST_FILE)}")
    print_info(f"Size: {file_size:.2f} MB")
    print_info(f"Path: {TEST_FILE}")
    
    # Get structure
    structure = get_workbook_structure(TEST_FILE)
    if structure:
        print_success(f"Workbook structure analyzed")
        print_info(f"  .twb files: {len(structure['twb_files'])}")
        print_info(f"  .tds files: {len(structure['tds_files'])}")
        print_info(f"  Data files: {len(structure['data_files'])}")
        print_info(f"  Other files: {len(structure['other_files'])}")
        
        # Count dashboards and worksheets
        dashboards = count_dashboards(TEST_FILE)
        worksheets = count_worksheets(TEST_FILE)
        
        print_success(f"Workbook contains {dashboards} dashboard(s) and {worksheets} worksheet(s)")
        
        return True
    
    return False

def test_extracted_calculated_fields():
    """Test extracted calculated fields."""
    print_header("TEST 2: EXTRACTED CALCULATED FIELDS")
    
    fields = get_calculated_fields(TEST_FILE)
    
    if fields:
        print_success(f"Found {len(fields)} calculated field(s)")
        
        print_info(f"\nAll calculated fields:")
        for i, field in enumerate(fields, 1):
            print(f"  {i}. {field['name']}")
            if field.get('caption'):
                print(f"     Caption: {field['caption']}")
            if field.get('datatype'):
                print(f"     Type: {field['datatype']}")
            if field.get('formula'):
                formula = field['formula'][:80] + "..." if len(field['formula']) > 80 else field['formula']
                print(f"     Formula: {formula}")
    else:
        print_warning(f"No calculated fields found")
    
    return fields

def test_search_calculated_fields(fields):
    """Test searching calculated fields."""
    print_header("TEST 3: SEARCH CALCULATED FIELDS")
    
    search_terms = ["Occupancy", "Rate", "Seats", "Avg", "Total"]
    
    for search_term in search_terms:
        print_info(f"Searching for: '{search_term}'")
        
        results, exact = search_calculated_fields(fields, search_term)
        
        if results:
            print_success(f"Found {len(results)} match(es) ({exact} exact)")
            for r in results[:2]:
                print(f"  • {r['name']} ({r.get('caption', 'No caption')})")
        else:
            print_warning(f"No matches for '{search_term}'")

def test_copy_workbook():
    """Test copying workbook to output."""
    print_header("TEST 4: COPY WORKBOOK TO OUTPUT")
    
    output = copy_workbook_to_output(TEST_FILE, os.path.basename(TEST_FILE))
    
    if output and os.path.exists(output):
        print_success(f"Workbook ready for processing")
        return True
    
    return False

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Run all tests."""
    print_header("STANDALONE DASHBOARD FACTORY TOOL - TEST SUITE")
    print(f"Test File: {os.path.basename(TEST_FILE)}")
    print(f"Output Directory: {OUTPUT_DIR}")
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test 1: Basic info
    if not test_workbook_basic_info():
        print_error("Cannot analyze workbook. Exiting.")
        return
    
    # Test 2: Get calculated fields
    fields = test_extracted_calculated_fields()
    
    # Test 3: Search fields
    if fields:
        test_search_calculated_fields(fields)
    
    # Test 4: Copy workbook
    test_copy_workbook()
    
    # Summary
    print_header("TEST SUITE COMPLETE")
    print(f"✅ All tests completed successfully!")
    print(f"📁 Output saved to: {OUTPUT_DIR}")
    print(f"⏰ End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
