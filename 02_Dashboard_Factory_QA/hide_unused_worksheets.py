"""
Hide Unused Worksheets Script
Analyzes a Tableau workbook and hides worksheets that are not used in any dashboard.
"""

import zipfile
import xml.etree.ElementTree as ET
import tempfile
import shutil
import os
from pathlib import Path


class UnusedWorksheetHider:
    """Hides unused worksheets in Tableau workbooks."""

    def __init__(self, twbx_path):
        """
        Initialize with workbook path.
        
        Args:
            twbx_path: Path to the .twbx file
        """
        self.twbx_path = twbx_path
        self.temp_dir = None
        self.twb_file = None
        self.namespace = None

    def extract_workbook(self):
        """Extract TWBX and locate .twb file."""
        self.temp_dir = tempfile.mkdtemp()
        print(f"Extracting workbook to: {self.temp_dir}")
        
        with zipfile.ZipFile(self.twbx_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        
        # Find .twb file
        for file in os.listdir(self.temp_dir):
            if file.endswith('.twb'):
                self.twb_file = os.path.join(self.temp_dir, file)
                print(f"Found workbook file: {file}")
                break
        
        if not self.twb_file:
            raise FileNotFoundError("No .twb file found in TWBX")

    def get_used_worksheets(self, root):
        """
        Get set of worksheet names used in dashboards.
        
        Args:
            root: XML root element
            
        Returns:
            Set of worksheet names used in dashboards
        """
        used_worksheets = set()
        
        # First, get all actual worksheet names (not parameters, not data sources)
        worksheet_tag = f'{self.namespace}worksheet' if self.namespace else 'worksheet'
        all_worksheet_names = set()
        for worksheet in root.findall(f'.//{worksheet_tag}'):
            name = worksheet.get('name')
            if name:
                all_worksheet_names.add(name)
        
        # Now look for viewpoints that reference actual worksheets
        windows_tag = f'{self.namespace}windows' if self.namespace else 'windows'
        windows = root.find(f'.//{windows_tag}')
        
        if windows is not None:
            viewpoint_tag = f'{self.namespace}viewpoint' if self.namespace else 'viewpoint'
            for viewpoint in windows.findall(f'.//{viewpoint_tag}'):
                name = viewpoint.get('name')
                # Only add if it's an actual worksheet name
                if name and name in all_worksheet_names:
                    used_worksheets.add(name)
                    print(f"  Found: worksheet '{name}' used in dashboard")
        
        return used_worksheets

    def hide_unused_worksheets(self):
        """Hide unused worksheets in the workbook."""
        print("\nParsing workbook XML...")
        tree = ET.parse(self.twb_file)
        root = tree.getroot()
        
        # Store namespace
        if '}' in root.tag:
            self.namespace = root.tag.split('}')[0] + '}'
        else:
            self.namespace = ''
        
        print("\nIdentifying used worksheets in dashboards...")
        used_worksheets = self.get_used_worksheets(root)
        
        print(f"\nTotal used worksheets: {len(used_worksheets)}")
        print(f"Used worksheets: {used_worksheets}")
        
        # Find all worksheets in worksheet definitions
        print("\nIdentifying all worksheet names...")
        all_worksheets = set()
        
        # With namespace
        ns_tag = f'{self.namespace}worksheet' if self.namespace else 'worksheet'
        for worksheet in root.findall(f'.//{ns_tag}'):
            name = worksheet.get('name')
            if name:
                all_worksheets.add(name)
        
        # Find unused worksheets
        unused_worksheets = all_worksheets - used_worksheets
        print(f"\nTotal worksheets: {len(all_worksheets)}")
        print(f"Total worksheets used in dashboards to hide: {len(used_worksheets)}")
        print(f"Worksheets that will be hidden: {used_worksheets}")
        
        # Hide worksheets that ARE used in dashboards
        # Find the windows section
        windows_tag = f'{self.namespace}windows' if self.namespace else 'windows'
        windows = root.find(f'.//{windows_tag}')
        
        if windows is not None:
            window_tag = f'{self.namespace}window' if self.namespace else 'window'
            for window in windows.findall(window_tag):
                name = window.get('name')
                window_class = window.get('class')
                
                # Hide worksheets that ARE used in dashboards
                if window_class == 'worksheet' and name in used_worksheets:
                    # Set hidden attribute
                    window.set('hidden', 'true')
                    print(f"  Hidden: '{name}'")
        
        # Save modified XML
        print("\nSaving modified workbook...")
        tree.write(self.twb_file, encoding='utf-8', xml_declaration=True)

    def save_workbook(self, output_path):
        """
        Repackage modified workbook.
        
        Args:
            output_path: Path where to save the modified workbook
        """
        print(f"Creating modified workbook: {output_path}")
        
        # Create new TWBX (which is a ZIP file)
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root_dir, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    file_path = os.path.join(root_dir, file)
                    arcname = os.path.relpath(file_path, self.temp_dir)
                    zipf.write(file_path, arcname)
        
        print(f"Workbook saved: {output_path}")

    def cleanup(self):
        """Remove temporary files."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            print("Temporary files cleaned up")

    def apply_modifications(self, output_path):
        """
        Complete workflow to hide unused worksheets.
        
        Args:
            output_path: Path where to save the modified workbook
        """
        try:
            self.extract_workbook()
            self.hide_unused_worksheets()
            self.save_workbook(output_path)
            print("\n✓ Successfully hid unused worksheets!")
        finally:
            self.cleanup()


def main():
    """Main function."""
    input_workbook = '/Users/RGaneshan/Desktop/Base Script/Transaction Management 2024.7 (3)_formatted.twbx'
    output_workbook = '/Users/RGaneshan/Desktop/Base Script/Transaction Management 2024.7 (3)_formatted_hidden_unused.twbx'
    
    if not os.path.exists(input_workbook):
        print(f"Error: Workbook not found at {input_workbook}")
        return
    
    print("=" * 70)
    print("Hide Unused Worksheets Tool")
    print("=" * 70)
    print(f"Input:  {input_workbook}")
    print(f"Output: {output_workbook}\n")
    
    hider = UnusedWorksheetHider(input_workbook)
    hider.apply_modifications(output_workbook)
    
    print("\nDone!")


if __name__ == '__main__':
    main()
