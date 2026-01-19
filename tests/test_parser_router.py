"""
Unit tests for parser router (AI parser decision logic)
"""
from scraper.ai.router import should_use_ai_parser


class TestShouldUseAIParser:
    """Test should_use_ai_parser function"""
    
    def test_simple_village_no_ai(self):
        """Simple villages should NOT use AI"""
        assert should_use_ai_parser("Aleksandravas") == False
        assert should_use_ai_parser("Aukštadvaris") == False
        assert should_use_ai_parser("Tarandė") == False
    
    def test_village_with_streets_no_ai(self):
        """Village with streets in parentheses should NOT use AI"""
        assert should_use_ai_parser("Avižieniai (Akacijų aklg., Avižų g.)") == False
        assert should_use_ai_parser("Bendoriai (Ateities g., Bendorėlių arka)") == False
    
    def test_house_numbers_use_ai(self):
        """Entries with house numbers SHOULD use AI"""
        assert should_use_ai_parser("Gilužiai Trumpoji g. (Nr. 1-1, 1-2, 5)") == True
        assert should_use_ai_parser("Sudervės g. 26, 28") == True
        assert should_use_ai_parser("Ilgoji g.,nuo 18 iki 18U") == True
    
    def test_ordinal_street_names_no_ai(self):
        """Ordinal street names (1-oji g.) are NOT house numbers"""
        assert should_use_ai_parser("Kalvių 1-oji, 2-oji, 3-oji g.") == False
        assert should_use_ai_parser("Žemaitukų 1-oji g.") == False
    
    def test_mixed_ordinal_and_house_numbers_use_ai(self):
        """Mix of ordinal streets AND house numbers SHOULD use AI"""
        assert should_use_ai_parser("Pikutiškės (Kalvių 1-oji, 2-oji g., Sudervės g. 26, 28)") == True
    
    def test_missing_commas_use_ai(self):
        """Missing commas between items SHOULD use AI"""
        # This would need a real example from CSV
    
    def test_streets_outside_parens_use_ai(self):
        """Streets outside parentheses SHOULD use AI"""
        # Example: "Bendoriai (streets) Žalumos g."
        assert should_use_ai_parser("Bendoriai (Ilgoji g.) Žalumos g.") == True
    
    def test_streets_without_parens_use_ai(self):
        """Streets without parentheses (directly after village) SHOULD use AI"""
        # Real case from CSV line 56: "Bezdonys Pakalnės g., Draugystės g."
        assert should_use_ai_parser("Bezdonys Pakalnės g., Draugystės g.") == True
        # Should NOT match simple village
        assert should_use_ai_parser("Bezdonys") == False
        # Should NOT match village with streets in parentheses
        assert should_use_ai_parser("Bezdonys (Pakalnės g., Draugystės g.)") == False
