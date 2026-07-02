import xml.etree.ElementTree as ET
import zipfile
import os
import tempfile
import shutil
from pathlib import Path


class WorksheetTitleModifier:
    """
    Modifies worksheet title styling in Tableau workbooks.
    Updates font size, font family, and color for all worksheet titles.
    """
    
    def __init__(self, tableau_file_path):
        """
        Initialize the worksheet title modifier.
        
        Args:
            tableau_file_path: Path to .twb or .twbx file
        """
        self.tableau_file_path = tableau_file_path
        self.is_twbx = tableau_file_path.lower().endswith('.twbx')
        self.workbook_xml = None
        self.temp_dir = None
        
        # Default styling for worksheet titles
        self.default_font_size = '15'
        self.default_font_family = 'Calibre'
        self.default_color = '#435254'
        self.default_font_style = 'normal'  # or 'bold', 'italic'
    
    def extract_workbook(self):
        """Extract TWBX file or read TBW XML."""
        if self.is_twbx:
            self.temp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(self.tableau_file_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)
            
            # Find the .twb file inside TWBX
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith('.twb'):
                        twb_path = os.path.join(root, file)
                        tree = ET.parse(twb_path)
                        self.workbook_xml = tree.getroot()
                        self.twb_path = twb_path
                        break
        else:
            # For .twb files, read directly
            tree = ET.parse(self.tableau_file_path)
            self.workbook_xml = tree.getroot()
            self.twb_path = self.tableau_file_path
    
    def modify_worksheet_titles(self, font_size=None, font_family=None, 
                               color=None, font_style=None):
        """
        Modify worksheet title styling.
        
        Args:
            font_size: Font size (e.g., '15')
            font_family: Font family (e.g., 'Calibre')
            color: Color hex code (e.g., '#435254')
            font_style: Font style ('normal', 'bold', 'italic')
        """
        if not self.workbook_xml:
            self.extract_workbook()
        
        # Use defaults if not provided
        font_size = font_size or self.default_font_size
        font_family = font_family or self.default_font_family
        color = color or self.default_color
        font_style = font_style or self.default_font_style
        
        modified_count = 0
        
        # Register namespace to preserve XML structure
        namespaces = {
            '': 'http://tableauserver.com/api',
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
        }
        
        for ns, url in namespaces.items():
            ET.register_namespace(ns, url)
        
        # Strategy 1: Find and update global worksheet title style rules (in workbook root)
        root_style = self.workbook_xml.find('style')
        if root_style is not None:
            for style_rule in root_style.findall('style-rule'):
                element_attr = style_rule.get('element')
                # Modify title, worksheet-title, and dash-title style rules
                if element_attr in ['title', 'worksheet-title', 'sheet-title', 'quick-filter-title', 'dash-title']:
                    
                    # Add/update format elements for our styles
                    if font_size:
                        self._update_or_create_format(style_rule, 'font-size', font_size)
                        modified_count += 1
                    
                    if font_family:
                        self._update_or_create_format(style_rule, 'font-family', font_family)
                        modified_count += 1
                    
                    if color:
                        self._update_or_create_format(style_rule, 'color', color)
                        modified_count += 1
                    
                    if font_style in ['bold', 'italic']:
                        if font_style == 'bold':
                            self._update_or_create_format(style_rule, 'font-weight', 'bold')
                        else:
                            self._update_or_create_format(style_rule, 'font-style', 'italic')
                        modified_count += 1
        
        # Strategy 2: Update title style rules within dashboards
        for dashboard in self.workbook_xml.findall('.//dashboard'):
            for style_rule in dashboard.findall('.//style-rule'):
                element_attr = style_rule.get('element')
                # Look for title-related style rules within dashboards
                if element_attr in ['title', 'worksheet-title', 'sheet-title', 'quick-filter-title']:
                    
                    if font_size:
                        self._update_or_create_format(style_rule, 'font-size', font_size)
                        modified_count += 1
                    
                    if font_family:
                        self._update_or_create_format(style_rule, 'font-family', font_family)
                        modified_count += 1
                    
                    if color:
                        self._update_or_create_format(style_rule, 'color', color)
                        modified_count += 1
                    
                    if font_style in ['bold', 'italic']:
                        if font_style == 'bold':
                            self._update_or_create_format(style_rule, 'font-weight', 'bold')
                        else:
                            self._update_or_create_format(style_rule, 'font-style', 'italic')
                        modified_count += 1
        
        # Strategy 3: Update title style rules within worksheets
        for worksheet in self.workbook_xml.findall('.//worksheet'):
            for style_rule in worksheet.findall('.//style-rule'):
                element_attr = style_rule.get('element')
                # Look for title styling in worksheets
                if element_attr in ['title', 'worksheet-title', 'sheet-title']:
                    
                    if font_size:
                        self._update_or_create_format(style_rule, 'font-size', font_size)
                        modified_count += 1
                    
                    if font_family:
                        self._update_or_create_format(style_rule, 'font-family', font_family)
                        modified_count += 1
                    
                    if color:
                        self._update_or_create_format(style_rule, 'color', color)
                        modified_count += 1
        
        # Strategy 4: Update formatted-text > run elements in worksheet titles
        # These are direct title stylings with fontcolor, fontsize, etc.
        for worksheet in self.workbook_xml.findall('.//worksheet'):
            title_elem = worksheet.find('.//layout-options/title')
            if title_elem is not None:
                # Search for formatted-text and run elements
                for run_elem in title_elem.findall('.//run'):
                    if font_size:
                        run_elem.set('fontsize', font_size)
                        modified_count += 1
                    
                    if color:
                        run_elem.set('fontcolor', color)
                        modified_count += 1
                    
                    # Note: fontfamily is not a valid attribute for run elements
                    # Only fontsize and fontcolor are supported
                    
                    if font_style == 'bold':
                        run_elem.set('bold', 'true')
                        modified_count += 1
                    elif font_style == 'italic':
                        run_elem.set('italic', 'true')
                        modified_count += 1
        
        # Strategy 5: Look for zone elements with type_v2='text' that are worksheet titles
        for zone in self.workbook_xml.findall('.//zone[@type_v2="text"]'):
            zone_style = zone.find('zone-style')
            if zone_style is not None:  # Only update if zone-style already exists
                # Update styling attributes
                if font_size:
                    self._update_zone_style(zone_style, 'font-size', font_size)
                    modified_count += 1
                
                if font_family:
                    self._update_zone_style(zone_style, 'font-family', font_family)
                    modified_count += 1
                
                if color:
                    self._update_zone_style(zone_style, 'color', color)
                    modified_count += 1
                
                if font_style:
                    self._update_zone_style(zone_style, 'font-style', font_style)
                    modified_count += 1
        
        # Strategy 6: Look for zones with type_v2='title' (dashboard title zones)
        for zone in self.workbook_xml.findall('.//zone[@type_v2="title"]'):
            zone_style = zone.find('zone-style')
            if zone_style is None:
                zone_style = ET.SubElement(zone, 'zone-style')
            
            # Update styling attributes
            if font_size:
                self._update_zone_style(zone_style, 'font-size', font_size)
                modified_count += 1
            
            if font_family:
                self._update_zone_style(zone_style, 'font-family', font_family)
                modified_count += 1
            
            if color:
                self._update_zone_style(zone_style, 'color', color)
                modified_count += 1
            
            if font_style:
                self._update_zone_style(zone_style, 'font-style', font_style)
                modified_count += 1
        
        return modified_count
    
    def _set_style_attr(self, element, attr_name, attr_value):
        """Set or update a style attribute in an element."""
        style = element.get('style', '')
        
        # Parse existing style
        style_dict = self._parse_style_string(style)
        style_dict[attr_name] = attr_value
        
        # Convert back to style string
        element.set('style', self._dict_to_style_string(style_dict))
    
    def _update_or_create_format(self, parent_elem, attr_name, attr_value):
        """Update or create a format element with the given attribute and value."""
        # Find existing format element with this attribute
        format_elem = parent_elem.find(f"format[@attr='{attr_name}']")
        
        if format_elem is None:
            # Create new format element
            format_elem = ET.SubElement(parent_elem, 'format')
            format_elem.set('attr', attr_name)
        
        format_elem.set('value', attr_value)
    
    def _update_zone_style(self, zone_style_elem, attr_name, attr_value):
        """Update a zone-style attribute."""
        # Find or create style element
        style_elem = zone_style_elem.find(f'style[@attribute="{attr_name}"]')
        if style_elem is None:
            style_elem = ET.SubElement(zone_style_elem, 'style')
            style_elem.set('attribute', attr_name)
        
        style_elem.set('value', attr_value)
    
    def _parse_style_string(self, style_str):
        """Parse CSS-like style string into dict."""
        style_dict = {}
        if style_str:
            for item in style_str.split(';'):
                if ':' in item:
                    key, value = item.split(':', 1)
                    style_dict[key.strip()] = value.strip()
        return style_dict
    
    def _dict_to_style_string(self, style_dict):
        """Convert style dict to CSS-like string."""
        return '; '.join([f'{k}: {v}' for k, v in style_dict.items()])
    
    def save_workbook(self, output_path=None):
        """
        Save modified workbook.
        
        Args:
            output_path: Path to save modified workbook. If None, overwrites original.
        """
        if not output_path:
            output_path = self.tableau_file_path
        
        if self.is_twbx:
            # Save modified XML back to temp TWB
            tree = ET.ElementTree(self.workbook_xml)
            tree.write(self.twb_path, encoding='utf-8', xml_declaration=True)
            
            # Repackage TWBX
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, self.temp_dir)
                        zipf.write(file_path, arcname)
            
            # Cleanup temp directory
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        else:
            # For .twb files, save directly
            tree = ET.ElementTree(self.workbook_xml)
            tree.write(output_path, encoding='utf-8', xml_declaration=True)
    
    def apply_modifications(self, output_path=None, font_size=None, 
                           font_family=None, color=None, font_style=None):
        """
        Complete workflow: extract, modify, and save.
        
        Args:
            output_path: Path to save modified workbook
            font_size: Font size for worksheet titles
            font_family: Font family for worksheet titles
            color: Color for worksheet titles
            font_style: Font style for worksheet titles
        
        Returns:
            Number of elements modified
        """
        self.extract_workbook()
        modified_count = self.modify_worksheet_titles(
            font_size=font_size,
            font_family=font_family,
            color=color,
            font_style=font_style
        )
        self.save_workbook(output_path)
        return modified_count


# Example usage function
def format_worksheet_titles(tableau_file_path, output_path=None, 
                           font_size='15', font_family='Calibre', 
                           color='#435254', font_style='normal'):
    """
    Format worksheet titles in a Tableau workbook.
    
    Args:
        tableau_file_path: Path to .twb or .twbx file
        output_path: Path to save formatted workbook
        font_size: Font size (default: '15')
        font_family: Font family (default: 'Calibre')
        color: Text color (default: '#435254')
        font_style: Font style (default: 'normal')
    
    Returns:
        Dictionary with modification details
    """
    modifier = WorksheetTitleModifier(tableau_file_path)
    modified_count = modifier.apply_modifications(
        output_path=output_path,
        font_size=font_size,
        font_family=font_family,
        color=color,
        font_style=font_style
    )
    
    return {
        'status': 'success',
        'file': output_path or tableau_file_path,
        'elements_modified': modified_count,
        'font_size': font_size,
        'font_family': font_family,
        'color': color,
        'font_style': font_style
    }


if __name__ == '__main__':
    """
    Interactive mode: Ask for input if no arguments provided
    Usage: python worksheet_title.py [input_file] [output_file] [font_size] [font_family] [color] [font_style]
    """
    import sys
    
    # If arguments provided, use them
    if len(sys.argv) >= 2:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        font_size = sys.argv[3] if len(sys.argv) > 3 else '15'
        font_family = sys.argv[4] if len(sys.argv) > 4 else 'Calibre'
        color = sys.argv[5] if len(sys.argv) > 5 else '#435254'
        font_style = sys.argv[6] if len(sys.argv) > 6 else 'normal'
    else:
        # Interactive mode: Ask for inputs
        print("\n" + "=" * 70)
        print("🎨 Worksheet Title Formatter - Interactive Mode")
        print("=" * 70)
        
        # Get input file
        while True:
            input_file = input("\n📁 Enter path to Tableau workbook (.twb or .twbx): ").strip()
            if not input_file:
                print("❌ Path cannot be empty. Please try again.")
                continue
            if not os.path.exists(input_file):
                print(f"❌ File not found: {input_file}")
                continue
            break
        
        # Get output file
        output_file = input("📁 Enter output file path (press Enter to overwrite input): ").strip()
        if not output_file:
            output_file = None
        
        # Get font size
        font_size = input("✏️  Enter font size (default: 15): ").strip() or '15'
        
        # Get font family
        font_family = input("✏️  Enter font family (default: Calibre): ").strip() or 'Calibre'
        
        # Get color
        color = input("🎨 Enter color hex code (default: #435254): ").strip() or '#435254'
        
        # Get font style
        font_style = input("✏️  Enter font style - normal/bold/italic (default: normal): ").strip() or 'normal'
    
    print("\n" + "=" * 70)
    print("🎨 Worksheet Title Formatter")
    print("=" * 70)
    print(f"📁 Input:        {input_file}")
    print(f"📁 Output:       {output_file or 'Same as input (will overwrite)'}")
    print(f"✏️  Font Size:    {font_size}")
    print(f"✏️  Font Family:  {font_family}")
    print(f"🎨 Color:        {color}")
    print(f"✏️  Font Style:   {font_style}")
    print("=" * 70)
    
    try:
        # Validate input file exists
        if not os.path.exists(input_file):
            print(f"❌ Error: Input file not found: {input_file}")
            sys.exit(1)
        
        # Format worksheet titles
        print("\n🔄 Processing...")
        result = format_worksheet_titles(
            tableau_file_path=input_file,
            output_path=output_file,
            font_size=font_size,
            font_family=font_family,
            color=color,
            font_style=font_style
        )
        
        # Display results
        print("\n✅ Success!")
        print(f"📝 Elements Modified: {result['elements_modified']}")
        print(f"💾 Output File: {result['file']}")
        print(f"🎨 Formatting Applied:")
        print(f"   - Font Size: {result['font_size']}")
        print(f"   - Font Family: {result['font_family']}")
        print(f"   - Color: {result['color']}")
        print(f"   - Font Style: {result['font_style']}")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
