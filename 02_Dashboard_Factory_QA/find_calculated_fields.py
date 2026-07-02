"""
Find Calculated Fields Tool
Searches for a term in all calculated fields and displays where it's used with the calculation
"""

import zipfile
import xml.etree.ElementTree as ET
import os
import re
from datetime import datetime


class CalculatedFieldsFinder:
    def __init__(self, workbook_path):
        self.workbook_path = workbook_path
        self.temp_dir = f"temp_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.calculated_fields = []
        self.field_map = {}  # Map field names to their human-readable captions

    def extract_workbook(self):
        """Extract TWBX file to temporary directory"""
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
            with zipfile.ZipFile(self.workbook_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)
            return True
        except Exception as e:
            print(f"✗ Error extracting workbook: {e}")
            return False

    def find_twb_file(self):
        """Find the main .twb file in the extracted directory"""
        try:
            # Check direct paths first
            direct_paths = [
                os.path.join(self.temp_dir, 'dataSource.tds'),
                os.path.join(self.temp_dir, 'workbook.twb'),
            ]
            
            for path in direct_paths:
                if os.path.exists(path):
                    return path
            
            # Search in first level
            for item in os.listdir(self.temp_dir):
                if item.endswith('.twb') or item.endswith('.tds'):
                    return os.path.join(self.temp_dir, item)
            
            # Search nested (limited depth)
            for item in os.listdir(self.temp_dir):
                item_path = os.path.join(self.temp_dir, item)
                if os.path.isdir(item_path):
                    for subitem in os.listdir(item_path):
                        if subitem.endswith('.twb') or subitem.endswith('.tds'):
                            return os.path.join(item_path, subitem)
            
            return None
        except Exception as e:
            print(f"Error finding TWB file: {e}")
            return None

    def extract_calculated_fields(self):
        """Extract all calculated fields from ALL datasources and workbook files"""
        try:
            calc_fields = []
            seen_names = set()
            
            # First pass: Build field map from all files
            self.field_map = {}
            
            # Find ALL .twb and .tds files
            xml_files = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith('.twb') or file.endswith('.tds'):
                        xml_files.append(os.path.join(root, file))
            
            if not xml_files:
                print(f"✗ Could not find any TWB or TDS files")
                return False
            
            print(f"📄 Found {len(xml_files)} XML files to search")
            
            # Process all XML files
            for xml_file in xml_files:
                try:
                    print(f"   Processing: {os.path.basename(xml_file)}")
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                    
                    # Build field map from this file
                    for col in root.iter('column'):
                        col_name = col.get('name', '')
                        col_caption = col.get('caption', '')
                        if col_name:
                            self.field_map[col_name] = col_caption if col_caption else col_name
                    
                    # Extract calculated fields from this file
                    for col in root.iter('column'):
                        col_name = col.get('name', '')
                        col_caption = col.get('caption', '')
                        
                        # Check if this column has a calculation child
                        calc_elem = col.find('calculation')
                        if calc_elem is not None:
                            formula = calc_elem.get('formula', '')
                            
                            # Avoid duplicates
                            if col_name and col_name not in seen_names:
                                datasource_name = os.path.basename(xml_file).replace('.tds', '').replace('.twb', '')
                                calc_fields.append({
                                    'datasource': datasource_name,
                                    'name': col_name,
                                    'caption': col_caption,
                                    'formula': formula if formula else 'No formula found'
                                })
                                seen_names.add(col_name)
                                print(f"      ✓ Found: {col_caption or col_name}")
                
                except Exception as e:
                    print(f"   ⚠ Error parsing {os.path.basename(xml_file)}: {e}")
                    continue
            
            self.calculated_fields = calc_fields
            print(f"✓ Total calculated fields found: {len(calc_fields)}")
            return True
            
        except Exception as e:
            print(f"Error extracting calculated fields: {e}")
            import traceback
            traceback.print_exc()
            return False

    def resolve_formula(self, formula):
        """Replace internal field references with their human-readable names"""
        if not formula:
            return formula
        
        resolved = formula
        # Replace all [FieldName] references with [Caption] if available
        
        def replace_field(match):
            field_ref = match.group(0)  # e.g., [Calculation_2070529967367172096]
            field_name_clean = match.group(1)  # e.g., Calculation_2070529967367172096
            
            # Look up the caption for this field (try with brackets first)
            if field_ref in self.field_map:
                caption = self.field_map[field_ref]
                # Return the caption, keeping it bracketed if needed 
                if not caption.startswith('['):
                    return f"[{caption}]"
                return caption
            elif field_name_clean in self.field_map:
                caption = self.field_map[field_name_clean]
                if not caption.startswith('['):
                    return f"[{caption}]"
                return caption
            return field_ref
        
        # Replace all [xxx] patterns
        resolved = re.sub(r'\[([^\]]+)\]', replace_field, resolved)
        return resolved

    def search_calculated_fields(self, search_term):
        """Search for a term ONLY in calculated field formulas (not in names or captions)"""
        try:
            if not search_term or len(search_term.strip()) == 0:
                return {'error': 'Search term cannot be empty', 'results': []}
            
            search_term_lower = search_term.lower()
            results = []
            
            for field in self.calculated_fields:
                # Search ONLY in formula - this is the key change
                formula_match = False
                if field['formula']:
                    formula_match = search_term_lower in field['formula'].lower()
                
                # Only add results if the search term is found in the FORMULA
                if formula_match:
                    # Resolve the formula to show human-readable field names
                    resolved_formula = self.resolve_formula(field['formula'])
                    
                    results.append({
                        'datasource': field['datasource'],
                        'name': field['name'],
                        'caption': field['caption'],
                        'formula': field['formula'],
                        'resolved_formula': resolved_formula,
                        'match_location': {
                            'name': False,  # Not searching in names anymore
                            'caption': False,  # Not searching in captions anymore
                            'formula': formula_match  # Only formula matches
                        }
                    })
            
            return {
                'search_term': search_term,
                'total_calculated_fields': len(self.calculated_fields),
                'matches_found': len(results),
                'results': results
            }
            
        except Exception as e:
            print(f"Error searching calculated fields: {e}")
            return {'error': str(e), 'results': []}

    def cleanup(self):
        """Remove temporary directory"""
        try:
            if os.path.exists(self.temp_dir):
                import shutil
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            return True
        except:
            return True

    def search(self, search_term):
        """Main workflow: extract, search, cleanup"""
        if not self.extract_workbook():
            return {'error': 'Failed to extract workbook', 'results': []}
        
        if not self.extract_calculated_fields():
            self.cleanup()
            return {'error': 'Failed to extract calculated fields', 'results': []}
        
        results = self.search_calculated_fields(search_term)
        self.cleanup()
        
        return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python find_calculated_fields.py <workbook_path> <search_term>")
        sys.exit(1)
    
    workbook = sys.argv[1]
    search_term = sys.argv[2]
    
    if not os.path.exists(workbook):
        print(f"✗ Workbook not found: {workbook}")
        sys.exit(1)
    
    finder = CalculatedFieldsFinder(workbook)
    results = finder.search(search_term)
    
    import json
    print(json.dumps(results, indent=2))
