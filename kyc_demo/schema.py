"""Output schema the LLM must follow (enforced via Gemini structured output)."""
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class DocType(str, Enum):
    passport = "passport"
    national_id = "national_id"
    drivers_licence = "drivers_licence"
    proof_of_address = "proof_of_address"          # utility bill, bank statement, etc.
    bank_statement = "bank_statement"
    certificate_of_incorporation = "certificate_of_incorporation"  # business licence / commercial registration
    register_of_directors = "register_of_directors"
    other = "other"


class ExtractedField(BaseModel):
    name: str = Field(description="English snake_case field name, e.g. company_name, registration_number")
    value_original: str = Field(description="Value exactly as written in the document, original script")
    value_english: str = Field(description="English translation / romanisation of the value")
    confidence: float = Field(description="0-1 confidence that the value was read and translated correctly")


class KYCDocument(BaseModel):
    doc_type: DocType
    source_language: str = Field(description="Main language of the document, e.g. Chinese (Simplified), Arabic")
    subject_name_original: str = Field(description="Person or entity name in original script; empty string if none")
    subject_name_english: str = Field(description="Name in English / standard romanisation (pinyin for Chinese)")
    name_variants: List[str] = Field(description="Other plausible English spellings of the name (useful for sanctions screening)")
    document_number: str = Field(description="ID / passport / registration / account number; empty if none")
    date_of_birth: str = Field(description="YYYY-MM-DD (Gregorian); empty if not applicable")
    issue_date: str = Field(description="YYYY-MM-DD (Gregorian); empty if none")
    expiry_date: str = Field(description="YYYY-MM-DD (Gregorian); empty if none")
    nationality_or_jurisdiction: str = Field(description="Nationality (person) or jurisdiction of registration (entity), in English")
    address_english: str = Field(description="Address translated into English; empty if none")
    issuing_authority_english: str = Field(description="Issuer / authority in English")
    calendar_notes: str = Field(description="Explain any non-Gregorian date conversions (e.g. Hijri to Gregorian); empty if none")
    mrz_lines: List[str] = Field(description="Machine Readable Zone lines (the <<< lines at the bottom of passports/ID cards), "
                                             "transcribed character-by-character exactly as printed, one string per line; empty list if none")
    fields: List[ExtractedField] = Field(description="All other key-value fields found on the document")
    full_translation_english: str = Field(description="Faithful English translation of the full document text")
    overall_confidence: float = Field(description="0-1 overall confidence in the extraction")
    review_flags: List[str] = Field(description="Issues a KYC analyst should check: illegible parts, possible alterations, inconsistencies, missing signature/stamp, etc.")
