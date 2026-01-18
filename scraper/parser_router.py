"""
Parser router - Determines whether to use traditional parser or AI parser
"""
import re


def should_use_ai_parser(kaimai_str: str) -> bool:
    """
    Determine if location string needs AI parsing
    
    Returns True if:
    - Contains house numbers (nuo, iki, Nr., numbers after street names)
    - Contains hyphenated numbers (X-Y pattern)
    - Missing commas between items
    - Streets outside parentheses
    - Complex nested structures
    
    Args:
        kaimai_str: Location string from Kaimai column
    
    Returns:
        True if AI parser should be used, False for traditional parser
    """
    # Check for house number indicators
    # Note: Ordinal street names (X-oji g.) are part of street names and handled by traditional parser
    # Only match actual house numbers (numbers after street names, nuo/iki, Nr., etc.)
    has_house_numbers = (
        re.search(r'\bnuo\b.*\biki\b', kaimai_str, re.IGNORECASE) or  # "nuo X iki Y"
        re.search(r'\bNr\.?\s*\d+', kaimai_str, re.IGNORECASE) or  # "Nr. 26"
        re.search(r'\d+-\d+[A-Z]?', kaimai_str) or  # Hyphenated house numbers: 1-1, 18-18U
        # Street followed by number list (house numbers): "g. 26, 28" or "g. 26 28"
        re.search(r'[a-ząčęėįšųūž]+\.?\s+\d+[,\s]+\d+', kaimai_str, re.IGNORECASE) or
        # Street followed by single number (house number): "g. 26" but NOT "g. 1-oji"
        (re.search(r'[a-ząčęėįšųūž]+\.?\s+\d+', kaimai_str, re.IGNORECASE) and
         not re.search(r'[a-ząčęėįšųūž]+\.?\s+\d+-oji', kaimai_str, re.IGNORECASE))
    )
    
    # Check for missing commas (street names without commas between)
    has_missing_commas = re.search(r'[a-ząčęėįšųūž]+\.\s+[A-ZĄČĘĖĮŠŲŪŽ]', kaimai_str)
    
    # Check for streets outside parentheses
    # Only flag if there ARE parentheses but also text outside them
    has_streets_outside = (
        '(' in kaimai_str and  # Has parentheses
        re.search(r'\)\s+[A-ZĄČĘĖĮŠŲŪŽ]', kaimai_str)  # Text after closing paren
    )
    
    return bool(has_house_numbers or has_missing_commas or has_streets_outside)
