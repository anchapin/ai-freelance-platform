"""
Template Library for Zero-Shot Document Generation

This module provides pre-tested Python script templates for standard deliverables.
Instead of asking the LLM to generate Python code from scratch, the system
now asks the LLM to output structured JSON content, which is then injected
into these pre-tested templates.

Benefits:
- Guarantees formatting won't throw Python errors
- Heavily reduces token usage
- Provides consistent, reliable document generation
- Easier to maintain and update templates

Usage:
    from src.templates import TemplateRegistry, generate_document
    
    # Get a template for legal contracts
    template = TemplateRegistry.get_template("legal_contract")
    
    # Generate content as JSON from LLM
    content_json = {
        "title": "Service Agreement",
        "parties": [...],
        "terms": [...]
    }
    
    # Inject into template and execute
    result = template.generate(content_json, csv_data)
"""

from src.templates.base_document import BaseDocumentTemplate
from src.templates.legal_contract import LegalContractTemplate
from src.templates.financial_summary import FinancialSummaryTemplate


class TemplateRegistry:
    """Registry for all document templates."""
    
    _templates = {
        "base": BaseDocumentTemplate,
        "legal_contract": LegalContractTemplate,
        "financial_summary": FinancialSummaryTemplate,
        # Add more templates here as needed
    }
    
    @classmethod
    def get_template(cls, template_name: str):
        """
        Get a template by name.
        
        Args:
            template_name: Name of the template to retrieve
            
        Returns:
            Template class or None if not found
        """
        return cls._templates.get(template_name)
    
    @classmethod
    def list_templates(cls) -> list:
        """List all available template names."""
        return list(cls._templates.keys())
    
    @classmethod
    def register_template(cls, name: str, template_class):
        """Register a new template."""
        cls._templates[name] = template_class


def generate_document(
    template_name: str,
    content_json: dict,
    csv_data: str,
    output_format: str = "docx",
    **kwargs
) -> dict:
    """
    Generate a document using a template.
    
    Args:
        template_name: Name of the template to use
        content_json: Structured JSON content from LLM
        csv_data: CSV data as string
        output_format: Output format (docx or pdf)
        **kwargs: Additional arguments
        
    Returns:
        Dictionary with generation results
    """
    template_class = TemplateRegistry.get_template(template_name)
    if not template_class:
        return {
            "success": False,
            "message": f"Template '{template_name}' not found"
        }
    
    template = template_class()
    return template.generate(content_json, csv_data, output_format, **kwargs)
