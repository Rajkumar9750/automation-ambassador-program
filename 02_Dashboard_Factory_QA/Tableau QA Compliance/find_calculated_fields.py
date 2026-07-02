#!/usr/bin/env python3
"""Extract and search calculated fields from Tableau workbooks."""

import os
import zipfile
import xml.etree.ElementTree as ET
import shutil
import tempfile
import re
from pathlib import Path


class CalculatedFieldsFinder:
    """Extract and search calculated fields from Tableau workbooks (.twb, .twbx)."""
    
    def __init__(self, filepath):
        """Initialize with a Tableau workbook file."""
        self.filepath = filepath
        self.temp_dir = None
        self.calculated_fields = []
        self.workbook_type = 'twbx' if filepath.lower().endswith('.twbx') else 'twb'
        
    def extract_workbook(self):
        """Extract the workbook archive to a temporary directory."""
        try:
            print(f"📦 Extracting workbook: {self.filepath}")
            
            # Create temporary directory
            self.temp_dir = tempfile.mkdtemp(prefix='tableau_workbook_')
            print(f"   Temp dir: {self.temp_dir}")
            
            # Extract if it's a TWBX (ZIP archive)
            if self.workbook_type == 'twbx':
                try:
                    with zipfile.ZipFile(self.filepath, 'r') as zip_ref:
                        zip_ref.extractall(self.temp_dir)
                    print(f"   ✓ Extracted TWBX successfully")
                except zipfile.BadZipFile:
                    print(f"   ❌ Not a valid ZIP file")
                    return False
            else:
                # For TWB files, just copy to temp directory
                shutil.copy(self.filepath, os.path.join(self.temp_dir, os.path.basename(self.filepath)))
                print(f"   ✓ Copied TWB file")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Error extracting workbook: {e}")
            return False
    
    def extract_calculated_fields(self):
        """Extract all calculated fields from the workbook."""
        try:
            if not self.temp_dir or not os.path.exists(self.temp_dir):
                print("❌ Temporary directory not found")
                return False
            
            print(f"🔍 Searching for calculated fields...")
            
            # Find all .twb and .tds files in the extracted directory
            field_map = {}  # {(datasource, field_id): field_info}
            
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith('.twb') or file.endswith('.tds'):
                        filepath = os.path.join(root, file)
                        print(f"   Parsing: {file}")
                        self._extract_fields_from_file(filepath, field_map)
            
            if not field_map:
                print("   ⚠️  No calculated fields found")
                self.calculated_fields = []
                return True
            
            # Convert to list format
            self.calculated_fields = list(field_map.values())
            print(f"   ✓ Found {len(self.calculated_fields)} calculated field(s)")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Error extracting calculated fields: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _extract_fields_from_file(self, filepath, field_map):
        """Extract calculated fields from a single TWB/TDS XML file."""
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            
            # Handle namespace
            namespaces = {'': 'http://tableauserveur.com/api'}
            
            # Find all datasources
            for datasource in root.findall('.//datasource', namespaces):
                datasource_name = datasource.get('name', 'Unknown')
                
                # Find calculated fields
                for calc_field in datasource.findall('.//column[@caption]', namespaces):
                    field_type = calc_field.get('type', '')
                    field_role = calc_field.get('role', '')
                    
                    # Check if this is a calculated field by looking for calculation element
                    calculation = calc_field.find('.//calculation', namespaces)
                    if calculation is not None:
                        field_id = calc_field.get('name', '')
                        field_caption = calc_field.get('caption', field_id)
                        formula = calculation.get('formula', '')
                        
                        if field_id and formula:
                            key = (datasource_name, field_id)
                            field_map[key] = {
                                'name': field_id,
                                'caption': field_caption,
                                'datasource': datasource_name,
                                'formula': formula,
                                'type': field_type,
                                'role': field_role
                            }
                            print(f"      Found: {field_caption} ({field_id})")
        
        except ET.ParseError as e:
            print(f"      ⚠️  XML parse error: {e}")
        except Exception as e:
            print(f"      ⚠️  Error processing file: {e}")
    
    def search(self, search_term):
        """Search for exact field name or field caption match in calculated fields."""
        try:
            print(f"\n🔍 Searching for exact match: '{search_term}'")
            
            # If fields haven't been extracted yet, do it now
            if not self.calculated_fields:
                if not self.extract_workbook():
                    return {'error': 'Failed to extract workbook', 'results': []}
                if not self.extract_calculated_fields():
                    return {'error': 'Failed to extract calculated fields', 'results': []}
            
            exact_results = []  # Exact field name/caption matches
            partial_results = []  # Formula matches
            search_lower = search_term.lower()
            
            for field in self.calculated_fields:
                field_name = field.get('name', '').lower()
                field_caption = field.get('caption', '').lower()
                formula = field.get('formula', '')
                
                # Check for exact field name or caption match
                if field_name == search_lower or field_caption == search_lower:
                    exact_results.append({
                        'name': field['name'],
                        'caption': field['caption'],
                        'datasource': field['datasource'],
                        'formula': formula,
                        'resolved_formula': formula,
                        'match_type': 'exact_field'
                    })
                # Check if search term is in formula (as fallback)
                elif search_lower in formula.lower():
                    partial_results.append({
                        'name': field['name'],
                        'caption': field['caption'],
                        'datasource': field['datasource'],
                        'formula': formula,
                        'resolved_formula': formula,
                        'match_type': 'formula_contains'
                    })
            
            # Combine results: exact matches first, then partial matches
            all_results = exact_results + partial_results
            
            print(f"✅ Found {len(all_results)} matching field(s) ({len(exact_results)} exact, {len(partial_results)} in formula)")
            
            return {
                'success': True,
                'total_calculated_fields': len(self.calculated_fields),
                'matches_found': len(all_results),
                'exact_matches': len(exact_results),
                'results': all_results
            }
            
        except Exception as e:
            print(f"❌ Error searching: {e}")
            import traceback
            traceback.print_exc()
            return {
                'error': str(e),
                'total_calculated_fields': 0,
                'matches_found': 0,
                'results': []
            }
    
    def cleanup(self):
        """Clean up temporary files."""
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                print(f"🧹 Cleaned up temporary directory")
        except Exception as e:
            print(f"⚠️  Error during cleanup: {e}")


if __name__ == '__main__':
    # Test
    import sys
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        finder = CalculatedFieldsFinder(filepath)
        if finder.extract_workbook() and finder.extract_calculated_fields():
            print(f"\nFound {len(finder.calculated_fields)} calculated fields:")
            for field in finder.calculated_fields:
                print(f"  - {field['caption']} ({field['datasource']})")
        finder.cleanup()
