"""
Delete Phone Layouts from Tableau Dashboards
Removes all phone device-specific layouts from dashboard XML
"""

import zipfile
import xml.etree.ElementTree as ET
import os
import shutil
from datetime import datetime


class PhoneLayoutDeleter:
    def __init__(self, workbook_path):
        self.workbook_path = workbook_path
        self.temp_dir = f"temp_workbook_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.xml_file = "dashboards/dashboards.xml"
        self.stats = {
            'dashboards_processed': 0,
            'phone_layouts_removed': 0,
            'dashboards_modified': 0
        }

    def extract_workbook(self):
        """Extract TWBX file to temporary directory"""
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
            with zipfile.ZipFile(self.workbook_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)
            print(f"✓ Extracted workbook to {self.temp_dir}")
            return True
        except Exception as e:
            print(f"✗ Error extracting workbook: {e}")
            return False

    def process_dashboards(self):
        """Remove phone layouts from all dashboards"""
        xml_path = os.path.join(self.temp_dir, self.xml_file)
        
        if not os.path.exists(xml_path):
            print(f"✗ Dashboards XML not found at {xml_path}")
            return False

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            
            # Process each dashboard
            for dashboard in root.findall('.//dashboard'):
                dashboard_name = dashboard.get('name', 'Unknown')
                self.stats['dashboards_processed'] += 1
                
                # Find all device layouts (phone layouts)
                phone_layouts_removed = self._remove_phone_layouts(dashboard)
                
                if phone_layouts_removed > 0:
                    self.stats['phone_layouts_removed'] += phone_layouts_removed
                    self.stats['dashboards_modified'] += 1
                    print(f"  ✓ {dashboard_name}: Removed {phone_layouts_removed} phone layout(s)")
                else:
                    print(f"  • {dashboard_name}: No phone layouts found")
            
            # Write modified XML back
            tree.write(xml_path, encoding='utf-8', xml_declaration=True)
            print(f"✓ Dashboards XML updated")
            return True
            
        except Exception as e:
            print(f"✗ Error processing dashboards: {e}")
            return False

    def _remove_phone_layouts(self, dashboard):
        """Remove phone device layouts from a dashboard"""
        removed_count = 0
        
        # Find all device-type elements that represent phone layouts
        # In Tableau, phone layouts are typically stored in device-type=phone
        device_layouts = dashboard.findall('.//device-layout[@type="phone"]')
        
        for device_layout in device_layouts:
            parent = dashboard.find('.//{*}*[device-layout]')
            # Iterate through dashboard children to find and remove phone device layouts
            for child in list(dashboard):
                if child.tag == 'device-layout' and child.get('type') == 'phone':
                    dashboard.remove(child)
                    removed_count += 1
        
        # Also check for device-generic elements that might contain phone layouts
        for device_generic in list(dashboard.findall('.//device-generic')):
            for child in list(device_generic):
                if child.tag == 'device-layout' and child.get('type') == 'phone':
                    device_generic.remove(child)
                    removed_count += 1
        
        return removed_count

    def repackage_workbook(self, output_path):
        """Repackage modified workbook back to TWBX"""
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
            
            def zipdir(path, ziph):
                for root, dirs, files in os.walk(path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, path)
                        ziph.write(file_path, arcname)
            
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipdir(self.temp_dir, zipf)
            
            print(f"✓ Repackaged workbook: {output_path}")
            return True
        except Exception as e:
            print(f"✗ Error repackaging workbook: {e}")
            return False

    def cleanup(self):
        """Remove temporary directory"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
            print(f"✓ Cleaned up temporary files")
            return True
        except Exception as e:
            print(f"✗ Error cleaning up: {e}")
            return False

    def apply_modifications(self, output_path):
        """Complete workflow: extract, process, repackage, cleanup"""
        print(f"\n{'='*60}")
        print("DELETING PHONE LAYOUTS FROM DASHBOARDS")
        print(f"{'='*60}\n")
        
        print("Step 1: Extracting workbook...")
        if not self.extract_workbook():
            return False
        
        print("\nStep 2: Processing dashboards...")
        if not self.process_dashboards():
            return False
        
        print("\nStep 3: Repackaging workbook...")
        if not self.repackage_workbook(output_path):
            return False
        
        print("\nStep 4: Cleaning up...")
        if not self.cleanup():
            return False
        
        # Print statistics
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Dashboards Processed: {self.stats['dashboards_processed']}")
        print(f"Phone Layouts Removed: {self.stats['phone_layouts_removed']}")
        print(f"Dashboards Modified: {self.stats['dashboards_modified']}")
        print(f"Output: {output_path}\n")
        
        return True


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python delete_phone_layouts.py <workbook_path> [output_path]")
        sys.exit(1)
    
    workbook = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else workbook.replace('.twbx', '_no_phone_layouts.twbx')
    
    if not os.path.exists(workbook):
        print(f"✗ Workbook not found: {workbook}")
        sys.exit(1)
    
    deleter = PhoneLayoutDeleter(workbook)
    success = deleter.apply_modifications(output)
    sys.exit(0 if success else 1)
