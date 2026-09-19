"""Mexico product-compliance overlay for existing TrustOS legal/tax packs.

This module is metadata-only. It encodes current Mexican import/sale
requirement *families* onto the canonical ``promotion.compliance`` gate.
It does not create a GATE_ID, scorer, registry, or live lookup.

Not legal advice. Not a tax conclusion. No SKU is certified by category.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping

from .control_plane import TrustControl, TrustEvidenceRequirement, _clean


PROMOTION_COMPLIANCE_GATE_ID = "compliance"
ACCESS_DATE = "2026-09-19"
LEGAL_DISCLAIMER = (
    "Not legal advice. TrustOS records requirement applicability and evidence "
    "gaps only; it does not conclude that a product is lawful to import or sell."
)

EVIDENCE_CLASSES = ("official_db", "supplier_claim", "fixture", "unknown")
LAUNCH_SATISFYING_EVIDENCE = frozenset({"official_db"})
NON_SATISFYING_EVIDENCE = frozenset({"supplier_claim", "fixture", "unknown", "manual"})
REQUIREMENT_STATUSES = ("needs_evidence", "not_assessed", "not_applicable", "satisfied")
REQUIREMENT_FAMILIES = ("import_customs", "labeling_safety", "telecom_homologation", "sector_permits", "tax_invoicing")
MARKETS = ("mexico", "united_states", "canada", "unknown")
NON_MEXICO_MARKETS = frozenset({"united_states", "canada"})
PRODUCT_FAMILIES = (
    "hydroponics_non_radio",
    "hydroponics_radio_iot",
    "smart_pet_wifi_2_4",
    "smart_pet_uncertain_band",
    "telecom_wifi_2_4",
    "telecom_dual_band",
    "telecom_cellular_4g",
    "unknown_family",
)
CONSUMER_DEVICE_FAMILIES = frozenset({
    "hydroponics_radio_iot", "smart_pet_wifi_2_4", "smart_pet_uncertain_band",
    "telecom_wifi_2_4", "telecom_dual_band", "telecom_cellular_4g",
})
NON_RADIO_FAMILIES = frozenset({"hydroponics_non_radio"})
RADIO_FAMILIES = frozenset({
    "hydroponics_radio_iot", "smart_pet_wifi_2_4", "smart_pet_uncertain_band",
    "telecom_wifi_2_4", "telecom_dual_band", "telecom_cellular_4g",
})
UNCERTAIN_OR_CELLULAR_FAMILIES = frozenset({
    "smart_pet_uncertain_band", "telecom_dual_band", "telecom_cellular_4g",
})
HYDRO_FAMILIES = frozenset({"hydroponics_non_radio", "hydroponics_radio_iot"})
BAND_2_4 = "2.4ghz"
BAND_5 = "5ghz"
BAND_6 = "6ghz"
CELLULAR_BANDS = frozenset({"cellular_4g", "cellular_5g"})
WIDE_BANDS = frozenset({BAND_5, BAND_6}) | CELLULAR_BANDS
COH_ACTIVE = "active"
COH_CANCELLED = "cancelled"

PRIVACY_LEGAL_PACK = "privacy_legal_baseline"
TAX_PACK = "tax_accounting_readiness"


@dataclass(frozen=True)
class MexicoPolicySource:
    source_id: str
    name: str
    authority: str
    url: str
    published: str
    effective: str
    accessed_at: str
    classification: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


def mexico_policy_sources() -> tuple[MexicoPolicySource, ...]:
    """Official citations recorded this session. Access date 2026-09-19."""
    accessed = ACCESS_DATE
    rows = (
        ("lmtr", "Ley en Materia de Telecomunicaciones y Radiodifusión", "Cámara de Diputados / DOF",
         "https://www.diputados.gob.mx/LeyesBiblio/pdf/LMTR.pdf", "2025-07-16", "2025-07-16", "verified_legal_text",
         "DOF 16 Jul 2025 codigo=5763167. Art. 3 XXXII homologación; art. 7 CRT órgano desconcentrado of ATDT; arts. 271-272 equipment that connects to a telecom network or uses radio spectrum must be homologated. Applicant domicile in Mexico."),
        ("lmtr-dof", "LMTR decreto DOF", "Diario Oficial de la Federación",
         "https://dof.gob.mx/nota_detalle.php?codigo=5763167&fecha=16/07/2025", "2025-07-16", "2025-07-16", "verified_legal_text",
         "Primary publication of the LMTR decree."),
        ("lmtr-index", "LMTR índice Cámara", "Cámara de Diputados",
         "https://www.diputados.gob.mx/LeyesBiblio/ref/lmtr.htm", "2025-07-16", "2025-07-16", "official_observation",
         "Index page for the LMTR original text."),
        ("lical", "Ley de Infraestructura de la Calidad", "Cámara de Diputados / DOF",
         "https://www.diputados.gob.mx/LeyesBiblio/pdf/LICal_010720.pdf", "2020-07-01", "2020-07-01", "verified_legal_text",
         "DOF 1 Jul 2020. Abroga the Ley Federal sobre Metrología y Normalización. Art. 1: observancia general. Art. 62: Evaluación de la Conformidad demonstrates compliance with NOMs or estándares. Cámara index reports sin reforma."),
        ("lfpc", "Ley Federal de Protección al Consumidor", "Cámara de Diputados / DOF",
         "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPC.pdf", "1992-12-24", "2025-12-12", "verified_legal_text",
         "Texto vigente; última reforma DOF 12-12-2025; actualización de montos DOF 23-12-2025. Art. 1: observancia en toda la República; information, safety, and advertising principles. PROFECO is the enforcing procuraduría."),
        ("lfpc-index", "LFPC índice Cámara", "Cámara de Diputados",
         "https://www.diputados.gob.mx/LeyesBiblio/ref/lfpc.htm", "1992-12-24", "2025-12-12", "official_observation",
         "Index confirming última reforma 12 Dec 2025."),
        ("ladua", "Ley Aduanera", "Cámara de Diputados / DOF",
         "https://www.diputados.gob.mx/LeyesBiblio/pdf/LAdua.pdf", "1995-12-15", "2025-11-19", "verified_legal_text",
         "Última reforma DOF 19-11-2025 (vigencia 1 Jan 2026 except listed transitorios). Art. 1: regulates entry/exit of merchandise and despacho aduanero. Pedimento and legal stay of foreign goods are customs-law questions; HS/TIGIE classification is required evidence, not inferred."),
        ("lgs", "Ley General de Salud", "Cámara de Diputados / DOF",
         "https://www.diputados.gob.mx/LeyesBiblio/pdf/LGS.pdf", "1984-02-07", "2026-01-15", "verified_legal_text",
         "Últimas reformas DOF 15-01-2026. Art. 1: reglamenta el derecho a la protección de la salud. Whether a given hydroponic nutrient or pet-food SKU is a COFEPRIS vs SADER/SENASICA input is unresolved without the exact product."),
        ("liva", "Ley del Impuesto al Valor Agregado", "Cámara de Diputados / DOF",
         "https://www.diputados.gob.mx/LeyesBiblio/pdf/LIVA.pdf", "1978-12-29", "2021-11-12", "verified_legal_text",
         "Art. 1: IVA on enajenación of goods and importación of goods or services in territorio nacional; tasa 16% as written in the retrieved text. Rate/exemptions for a SKU are accountant-reviewed, not guessed."),
        ("cff-sat-cfdi", "CFF arts. 29 y 29-A via SAT Anexo 20", "SAT / CFF",
         "https://wwwmat.sat.gob.mx/consultas/35025/formato-de-factura-electronica-(anexo-20)", "2022-01-01", "2023-04-01", "official_observation",
         "SAT official trámite page cites CFF arts. 29 and 29-A as fundamento of CFDI 4.0. Direct CFF PDF returned HTTP 503 this session; Cámara ref page is https://www.diputados.gob.mx/LeyesBiblio/ref/cff.htm. CFDI 4.0 is the only valid version from 1 Apr 2023 per SAT."),
        ("sat-anexo20", "SAT Anexo 20 CFDI 4.0", "SAT",
         "http://omawww.sat.gob.mx/tramitesyservicios/Paginas/anexo_20.htm", "2022-01-01", "2023-04-01", "official_observation",
         "SAT Anexo 20 page accessed 2026-09-19. Catalog file dated 18/09/2026 on that page."),
        ("nom-003", "NOM-003-SCFI-2014 Productos eléctricos-Especificaciones de seguridad", "Secretaría de Economía / DOF",
         "https://platiica.economia.gob.mx/normalizacion/nom-003-scfi-2014/", "2015-05-28", "2016-05-27", "official_observation",
         "PLATIICA (SE) catalog: vigente; DOF 28 May 2015; entrada en vigor 27 May 2016. Applies to electrical products using public power or batteries up to 1000 V AC / 1500 V DC. Exact DOF codigo not re-fetched this session."),
        ("nom-024", "NOM-024-SCFI-2013 Información comercial para empaques, instructivos y garantías", "Secretaría de Economía / DOF",
         "https://www.dof.gob.mx/nota_detalle.php?codigo=5309980&fecha=12/08/2013", "2013-08-12", "2013-10-11", "verified_legal_text",
         "DOF 12 Aug 2013 codigo=5309980. Commercial information on packaging, instructions, and warranties for electronic/electrical/household products sold in Mexico, including importer identity. PROFECO vigilará. PLATIICA lists vigencia 11 Oct 2013."),
        ("nom-024-platiica", "NOM-024-SCFI-2013 PLATIICA", "Secretaría de Economía",
         "https://platiica.economia.gob.mx/normalizacion/nom-024-scfi-2013/", "2013-08-12", "2013-10-11", "official_observation",
         "SE catalog confirming vigente / DOF 12/8/2013 / vigencia 11/10/2013."),
        ("nom-208", "NOM-208-SCFI-2016 espectro disperso 902/2400/5725 MHz", "Secretaría de Economía / DOF",
         "https://www.dof.gob.mx/nota_detalle.php?codigo=5471010&fecha=07/02/2017", "2017-02-07", "2017-04-08", "verified_legal_text",
         "DOF 7 Feb 2017 codigo=5471010. Spread-spectrum FHSS/digital modulation in 902-928 / 2400-2483.5 / 5725-5850 MHz must meet IFT-008-2015. PLATIICA: vigencia 8 Apr 2017."),
        ("nom-001-sede", "NOM-001-SEDE-2012 Instalaciones eléctricas (utilización)", "SENER / DOF",
         "https://dof.gob.mx/nota_detalle_popup.php?codigo=5280607", "2012-07-29", "2012-07-29", "official_observation",
         "Electrical *installations* (utilization), not consumer plug-in product safety. Default not_applicable for listed consumer SKU families unless the packet marks electrical_install_equipment."),
        ("ift-008", "Disposición Técnica IFT-008-2015", "IFT (archivo histórico)",
         "https://www.ift.org.mx/industria/normas-oficiales-mexicanas-y-disposiciones-tecnicas-correspondientes-la-homologacion", "2015-10-19", "2015-10-20", "official_observation",
         "IFT archive table: IFT-008-2015 DOF 19/10/2015. Site banner: historical archive; trámites pointed at gob.mx/crt. Unresolved whether CRT reissued this DT under its own name."),
        ("ift-016", "Disposición Técnica IFT-016-2024", "IFT (archivo histórico)",
         "https://www.ift.org.mx/industria/normas-oficiales-mexicanas-y-disposiciones-tecnicas-correspondientes-la-homologacion", "2025-02-07", "2025-11-03", "official_observation",
         "IFT archive table: IFT-016-2024 DOF 07/02/2025, vigente 03/11/2025 (low-power 30 MHz–3 GHz). Arithmetic 7 Feb 2025 + 270 days is 4 Nov 2025; treat the IFT table date as observation, not a guessed DT for a SKU."),
        ("ift-017", "Disposición Técnica IFT-017-2023", "IFT (archivo histórico)",
         "https://www.ift.org.mx/industria/normas-oficiales-mexicanas-y-disposiciones-tecnicas-correspondientes-la-homologacion", "2025-02-10", "2025-11-07", "official_observation",
         "IFT archive table: IFT-017-2023 DOF 10/02/2025, vigente 07/11/2025 (WLAN 5/6 GHz including 5925–6425 MHz). Do not guess this DT for dual-band SKUs without a test-report frequency table."),
        ("ehomologados", "Registro de equipos homologados", "IFT / CRT observation",
         "https://ehomologados.ift.org.mx/", "", "", "official_observation",
         "Official CoH search UI. This module never scrapes it. supplier_claim that a model is homologado is not an official_db row."),
        ("crt", "Comisión Reguladora de Telecomunicaciones", "CRT / gob.mx",
         "https://www.gob.mx/crt", "2025-10-16", "", "official_observation",
         "CRT Pleno integration is described in DOF recitals around 16 Oct 2025; IFT pages are archive. Unresolved: whether CRT republished IFT 2021 homologation lineamientos unchanged. Do not hard-code Tipo A/B/C."),
        ("cofepris", "Comisión Federal para la Protección contra Riesgos Sanitarios", "COFEPRIS / gob.mx",
         "https://www.gob.mx/cofepris", "", "", "official_observation",
         "Official agency page. Sanitary regulation of goods/services/health inputs. Exact SKU competence vs SADER/SENASICA for nutrients, seeds, or pet food is unresolved."),
        ("semarnat", "Secretaría de Medio Ambiente y Recursos Naturales", "SEMARNAT / gob.mx",
         "https://www.gob.mx/semarnat", "", "", "official_observation",
         "Official agency page. Hazardous materials / environmental authorizations are not inferred from category."),
        ("snice", "SNICE", "Secretaría de Economía / SNICE",
         "https://www.snice.gob.mx/", "", "", "unresolved_interpretation",
         "Import-permit / NOM-aduanera coordination surface. Not fetched as legal text this session; missing permits remain needs_evidence."),
    )
    return tuple(MexicoPolicySource(sid, name, authority, url, published, effective, accessed, classification, note)
                 for sid, name, authority, url, published, effective, classification, note in rows)


def _source_refs_for(*source_ids: str) -> tuple[str, ...]:
    catalog = {item.source_id: item for item in mexico_policy_sources()}
    refs = []
    for source_id in source_ids:
        item = catalog[source_id]
        refs.append(f"{item.name} | {item.url} | published={item.published} | accessed={item.accessed_at} | {item.classification}")
    refs.append(LEGAL_DISCLAIMER)
    return tuple(refs)


@dataclass(frozen=True)
class MexicoProductCompliancePacket:
    market: str
    product_family: str
    sku_model_exact: str = ""
    radio_present: bool | None = None
    radio_bands_observed: tuple[str, ...] = ()
    electrical_present: bool | None = None
    electrical_install_equipment: bool | None = None
    contains_nutrients_or_seeds: bool | None = None
    contains_hazardous_materials: bool | None = None
    origin_imported: bool | None = None
    immex_claimed: bool = False
    already_sold_in_mexico: bool = False
    hs_classification: str = ""
    importer_rfc: str = ""
    cfdi_ready: bool = False
    pedimento_ref: str = ""
    iva_treatment_reviewed: bool = False
    coh_number: str = ""
    coh_model: str = ""
    coh_status: str = ""
    coh_evidence_class: str = "unknown"
    nom_003_evidence_class: str = "unknown"
    nom_024_evidence_class: str = "unknown"
    lfpc_labeling_evidence_class: str = "unknown"
    cofepris_evidence_class: str = "unknown"
    semarnat_evidence_class: str = "unknown"
    rfc_evidence_class: str = "unknown"
    cfdi_evidence_class: str = "unknown"
    iva_evidence_class: str = "unknown"
    pedimento_evidence_class: str = "unknown"
    hs_evidence_class: str = "unknown"
    sources_accessed_at: str = ""
    as_of: str = ACCESS_DATE
    citation_freshness_days: int = 180

    def __post_init__(self) -> None:
        if self.market not in MARKETS:
            raise ValueError(f"unsupported market: {self.market}")
        if self.product_family not in PRODUCT_FAMILIES:
            raise ValueError(f"unsupported product family: {self.product_family}")
        for field_name in (
            "coh_evidence_class", "nom_003_evidence_class", "nom_024_evidence_class",
            "lfpc_labeling_evidence_class", "cofepris_evidence_class", "semarnat_evidence_class",
            "rfc_evidence_class", "cfdi_evidence_class", "iva_evidence_class",
            "pedimento_evidence_class", "hs_evidence_class",
        ):
            value = getattr(self, field_name)
            if value not in EVIDENCE_CLASSES:
                raise ValueError(f"unsupported evidence class for {field_name}: {value}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class MexicoRequirementResult:
    requirement_id: str
    family: str
    pack_id: str
    control_id: str
    status: str
    blocker: str
    note: str

    def __post_init__(self) -> None:
        if self.family not in REQUIREMENT_FAMILIES:
            raise ValueError(f"unsupported requirement family: {self.family}")
        if self.status not in REQUIREMENT_STATUSES:
            raise ValueError(f"unsupported requirement status: {self.status}")
        if self.pack_id not in {PRIVACY_LEGAL_PACK, TAX_PACK}:
            raise ValueError("Mexico requirements must map onto existing legal/tax packs")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class MexicoComplianceDecision:
    promotion_gate_id: str
    compliance_satisfied: bool
    market: str
    product_family: str
    sku_model_exact: str
    results: tuple[MexicoRequirementResult, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    not_legal_advice: bool = True
    live_lookup_performed: bool = False
    legal_conclusion: bool = False
    tax_conclusion: bool = False
    new_gate_created: bool = False

    def __post_init__(self) -> None:
        if self.promotion_gate_id != PROMOTION_COMPLIANCE_GATE_ID:
            raise ValueError("Mexico overlay must use the canonical promotion.compliance gate")
        if self.new_gate_created:
            raise ValueError("Mexico overlay must not create a second gate")
        if self.legal_conclusion or self.tax_conclusion or self.live_lookup_performed:
            raise ValueError("Mexico overlay must remain metadata-only")

    def requirement(self, requirement_id: str) -> MexicoRequirementResult:
        return next(item for item in self.results if item.requirement_id == requirement_id)

    def promotion_gate_satisfaction(self) -> dict[str, bool]:
        return {PROMOTION_COMPLIANCE_GATE_ID: self.compliance_satisfied}

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


def _parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def citation_is_stale(accessed_at: str, as_of: str, freshness_days: int) -> bool:
    accessed = _parse_day(accessed_at)
    as_of_day = _parse_day(as_of)
    if accessed is None or as_of_day is None:
        return True
    if accessed > as_of_day:
        return True
    return (as_of_day - accessed) > timedelta(days=int(freshness_days))


def _official(evidence_class: str, packet: MexicoProductCompliancePacket) -> bool:
    return evidence_class in LAUNCH_SATISFYING_EVIDENCE and not citation_is_stale(
        packet.sources_accessed_at, packet.as_of, packet.citation_freshness_days
    )


def _result(requirement_id: str, family: str, pack_id: str, status: str, *, blocker: str = "", note: str = "") -> MexicoRequirementResult:
    if status == "needs_evidence" and not blocker:
        blocker = f"{requirement_id}:needs_evidence"
    if status == "not_assessed" and not blocker:
        blocker = f"{requirement_id}:not_assessed"
    return MexicoRequirementResult(requirement_id, family, pack_id, f"control-{pack_id}-{requirement_id}", status, blocker, note)


def _from_evidence(requirement_id: str, family: str, pack_id: str, applicable: str, evidence_class: str, packet: MexicoProductCompliancePacket, *, extra_ok: bool = True, missing_note: str = "") -> MexicoRequirementResult:
    if applicable == "not_assessed":
        return _result(requirement_id, family, pack_id, "not_assessed", note="Mexico requirements are not assessed for this market.")
    if applicable == "not_applicable":
        return _result(requirement_id, family, pack_id, "not_applicable", note="Declared not applicable for this family/facts; not a legal pass.")
    if evidence_class in {"supplier_claim", "fixture", "manual"}:
        return _result(requirement_id, family, pack_id, "needs_evidence", blocker=f"{requirement_id}:non_official_evidence:{evidence_class}", note="supplier_claim/fixture/manual cannot satisfy launch compliance.")
    if extra_ok and _official(evidence_class, packet):
        return _result(requirement_id, family, pack_id, "satisfied", note="Official evidence present and citation is fresh. Not a legal conclusion.")
    note = missing_note or "Official, fresh, model-matched evidence is required."
    if citation_is_stale(packet.sources_accessed_at, packet.as_of, packet.citation_freshness_days) and evidence_class == "official_db":
        return _result(requirement_id, family, pack_id, "needs_evidence", blocker=f"{requirement_id}:stale_citation", note=note)
    return _result(requirement_id, family, pack_id, "needs_evidence", note=note)


def _market_applicable(packet: MexicoProductCompliancePacket) -> str:
    if packet.market == "mexico":
        return "applicable"
    return "not_assessed"


def _radio_applicable(packet: MexicoProductCompliancePacket) -> str:
    market = _market_applicable(packet)
    if market != "applicable":
        return market
    bands = tuple(str(item).lower() for item in packet.radio_bands_observed)
    if packet.product_family in NON_RADIO_FAMILIES and packet.radio_present is True:
        return "applicable"
    if packet.product_family in NON_RADIO_FAMILIES and bands:
        return "applicable"
    if packet.radio_present is False or packet.product_family in NON_RADIO_FAMILIES:
        return "not_applicable"
    if packet.radio_present is True or packet.product_family in RADIO_FAMILIES:
        return "applicable"
    return "applicable"


def _electrical_applicable(packet: MexicoProductCompliancePacket) -> str:
    market = _market_applicable(packet)
    if market != "applicable":
        return market
    if packet.electrical_present is False:
        return "not_applicable"
    if packet.electrical_present is True or packet.product_family in CONSUMER_DEVICE_FAMILIES:
        return "applicable"
    if packet.product_family in NON_RADIO_FAMILIES:
        return "applicable"
    return "applicable"


def _install_applicable(packet: MexicoProductCompliancePacket) -> str:
    market = _market_applicable(packet)
    if market != "applicable":
        return market
    if packet.electrical_install_equipment is True:
        return "applicable"
    if packet.electrical_install_equipment is False:
        return "not_applicable"
    if packet.product_family in PRODUCT_FAMILIES and packet.product_family != "unknown_family":
        return "not_applicable"
    return "applicable"


def _import_applicable(packet: MexicoProductCompliancePacket) -> str:
    market = _market_applicable(packet)
    if market != "applicable":
        return market
    if packet.origin_imported is False:
        return "not_applicable"
    return "applicable"


def _cofepris_applicable(packet: MexicoProductCompliancePacket) -> str:
    market = _market_applicable(packet)
    if market != "applicable":
        return market
    if packet.contains_nutrients_or_seeds is True:
        return "applicable"
    if packet.contains_nutrients_or_seeds is False:
        return "not_applicable"
    if packet.product_family in HYDRO_FAMILIES:
        return "applicable"
    return "not_applicable"


def _semarnat_applicable(packet: MexicoProductCompliancePacket) -> str:
    market = _market_applicable(packet)
    if market != "applicable":
        return market
    if packet.contains_hazardous_materials is True:
        return "applicable"
    if packet.contains_hazardous_materials is False:
        return "not_applicable"
    if packet.product_family in HYDRO_FAMILIES:
        return "applicable"
    return "not_applicable"


def _nom208_applicable(packet: MexicoProductCompliancePacket) -> str:
    radio = _radio_applicable(packet)
    if radio != "applicable":
        return radio
    bands = tuple(str(item).lower() for item in packet.radio_bands_observed)
    if packet.product_family in UNCERTAIN_OR_CELLULAR_FAMILIES or any(band in WIDE_BANDS for band in bands):
        return "not_applicable"
    if packet.product_family in {"smart_pet_wifi_2_4", "telecom_wifi_2_4"} or BAND_2_4 in bands:
        return "applicable"
    return "not_applicable"


def _coh_extra_ok(packet: MexicoProductCompliancePacket) -> tuple[bool, str]:
    if not packet.sku_model_exact.strip():
        return False, "Exact model is required before a CoH can satisfy homologation."
    if packet.coh_status == COH_CANCELLED:
        return False, "Cancelled CoH cannot satisfy launch compliance."
    if packet.coh_evidence_class == "official_db" and packet.coh_model.strip() and packet.coh_model.strip().lower() != packet.sku_model_exact.strip().lower():
        return False, "CoH model does not match the exact SKU model."
    if packet.coh_status and packet.coh_status not in {COH_ACTIVE, ""}:
        return False, "CoH status is not active."
    bands = tuple(str(item).lower() for item in packet.radio_bands_observed)
    if packet.product_family in UNCERTAIN_OR_CELLULAR_FAMILIES and not packet.coh_number:
        return False, "Dual-band/cellular families must not guess IFT-016/017/011; official CoH for the exact model is required."
    if any(band in WIDE_BANDS for band in bands) and not packet.coh_number:
        return False, "Observed 5/6 GHz or cellular bands: do not guess the technical disposition."
    if not packet.coh_number.strip() or packet.coh_status != COH_ACTIVE:
        return False, "Official CoH number with active status matching the exact model is required."
    return True, ""

def evaluate_mexico_product_compliance(packet: MexicoProductCompliancePacket | Mapping[str, Any]) -> MexicoComplianceDecision:
    if not isinstance(packet, MexicoProductCompliancePacket):
        packet = MexicoProductCompliancePacket(**dict(packet))
    from evaluation.commerce.promotion import GATE_IDS
    if PROMOTION_COMPLIANCE_GATE_ID not in GATE_IDS:
        raise ValueError("canonical promotion.compliance gate is missing")

    radio_applicable = _radio_applicable(packet)
    coh_ok, coh_note = _coh_extra_ok(packet) if radio_applicable == "applicable" else (True, "")
    if radio_applicable == "applicable" and packet.coh_status == COH_CANCELLED:
        coh_ok, coh_note = False, "Cancelled CoH cannot satisfy launch compliance."
    if radio_applicable == "applicable" and packet.coh_evidence_class == "official_db" and packet.coh_model.strip() and packet.sku_model_exact.strip() and packet.coh_model.strip().lower() != packet.sku_model_exact.strip().lower():
        coh_ok, coh_note = False, "CoH model does not match the exact SKU model."

    results = (
        _from_evidence("mx_hs_classification", "import_customs", TAX_PACK, _import_applicable(packet), packet.hs_evidence_class, packet, extra_ok=bool(packet.hs_classification.strip()), missing_note="Unknown HS/TIGIE classification remains needs_evidence."),
        _from_evidence("mx_pedimento", "import_customs", TAX_PACK, _import_applicable(packet), packet.pedimento_evidence_class, packet, extra_ok=bool(packet.pedimento_ref.strip()), missing_note="Pedimento / legal stay of foreign goods remains needs_evidence."),
        _from_evidence("mx_immex", "import_customs", TAX_PACK, "applicable" if _market_applicable(packet) == "applicable" and packet.immex_claimed else ("not_assessed" if _market_applicable(packet) != "applicable" else "not_applicable"), "unknown", packet, extra_ok=False, missing_note="IMMEX is only applicable when claimed; ordinary import does not require it."),
        _from_evidence("mx_importer_rfc", "tax_invoicing", TAX_PACK, _market_applicable(packet), packet.rfc_evidence_class, packet, extra_ok=bool(packet.importer_rfc.strip()), missing_note="Importer/seller RFC remains needs_evidence."),
        _from_evidence("mx_cfdi", "tax_invoicing", TAX_PACK, _market_applicable(packet), packet.cfdi_evidence_class, packet, extra_ok=packet.cfdi_ready, missing_note="CFDI 4.0 readiness remains needs_evidence."),
        _from_evidence("mx_iva", "tax_invoicing", TAX_PACK, _market_applicable(packet), packet.iva_evidence_class, packet, extra_ok=packet.iva_treatment_reviewed, missing_note="IVA treatment remains needs_evidence; this is not a tax conclusion."),
        _from_evidence("mx_nom_electrical_safety", "labeling_safety", PRIVACY_LEGAL_PACK, _electrical_applicable(packet), packet.nom_003_evidence_class, packet, missing_note="NOM-003-SCFI-2014 conformity evidence is required for electrical products."),
        _from_evidence("mx_nom_labeling", "labeling_safety", PRIVACY_LEGAL_PACK, _electrical_applicable(packet), packet.nom_024_evidence_class, packet, missing_note="NOM-024-SCFI-2013 Spanish labeling/instructions/warranty evidence is required."),
        _from_evidence("mx_nom_electrical_installations", "labeling_safety", PRIVACY_LEGAL_PACK, _install_applicable(packet), "unknown", packet, extra_ok=False, missing_note="NOM-001-SEDE-2012 applies to electrical installations, not typical plug-in SKUs."),
        _from_evidence("mx_lfpc_profeco", "labeling_safety", PRIVACY_LEGAL_PACK, _market_applicable(packet), packet.lfpc_labeling_evidence_class, packet, missing_note="LFPC/PROFECO consumer-information evidence remains needs_evidence."),
        _from_evidence("mx_infraestructura_calidad", "labeling_safety", PRIVACY_LEGAL_PACK, _market_applicable(packet), packet.lfpc_labeling_evidence_class, packet, missing_note="Ley de Infraestructura de la Calidad conformity-assessment evidence remains needs_evidence."),
        _from_evidence("mx_telecom_homologation", "telecom_homologation", PRIVACY_LEGAL_PACK, radio_applicable, packet.coh_evidence_class, packet, extra_ok=coh_ok, missing_note=coh_note or "Official CoH for the exact model is required; dual-band/cellular DTs are not guessed."),
        _from_evidence("mx_nom_208_radio", "telecom_homologation", PRIVACY_LEGAL_PACK, _nom208_applicable(packet), packet.coh_evidence_class, packet, extra_ok=coh_ok, missing_note="NOM-208/IFT-008 applies only when 2.4/ISM bands are confirmed; dual-band/cellular DTs are not guessed."),
        _from_evidence("mx_ley_general_salud", "sector_permits", PRIVACY_LEGAL_PACK, _cofepris_applicable(packet), packet.cofepris_evidence_class, packet, missing_note="Ley General de Salud / sanitary competence remains needs_evidence."),
        _from_evidence("mx_cofepris_sector", "sector_permits", PRIVACY_LEGAL_PACK, _cofepris_applicable(packet), packet.cofepris_evidence_class, packet, missing_note="COFEPRIS vs SADER/SENASICA competence is unresolved without the exact input; needs_evidence."),
        _from_evidence("mx_semarnat_sector", "sector_permits", PRIVACY_LEGAL_PACK, _semarnat_applicable(packet), packet.semarnat_evidence_class, packet, missing_note="SEMARNAT environmental authorization is not inferred from category."),
    )

    warnings = []
    if packet.already_sold_in_mexico:
        warnings.append("already_sold_in_mexico_does_not_clear_compliance")
    if packet.market in NON_MEXICO_MARKETS:
        warnings.append("non_mexico_market_not_assessed")
    bands = tuple(str(item).lower() for item in packet.radio_bands_observed)
    if any(band in WIDE_BANDS for band in bands):
        warnings.append("radio_disposition_not_guessed")
    if packet.product_family in UNCERTAIN_OR_CELLULAR_FAMILIES:
        warnings.append("uncertain_or_cellular_bands_hold_compliance")

    blockers: list[str] = []
    if not packet.sku_model_exact.strip() and packet.market == "mexico":
        blockers.append("missing_exact_sku_model")
    for item in results:
        if item.status == "needs_evidence" and item.blocker:
            blockers.append(item.blocker)
        elif item.status == "not_assessed" and packet.market != "mexico":
            continue
    if packet.market != "mexico":
        blockers.append("mexico_requirements_not_assessed")

    compliance = (
        packet.market == "mexico"
        and bool(packet.sku_model_exact.strip())
        and all(item.status in {"not_applicable", "satisfied"} for item in results)
    )
    return MexicoComplianceDecision(
        PROMOTION_COMPLIANCE_GATE_ID, compliance, packet.market, packet.product_family,
        packet.sku_model_exact, results, tuple(dict.fromkeys(blockers)), tuple(dict.fromkeys(warnings)),
    )


def build_mexico_trust_controls() -> tuple[TrustControl, ...]:
    """Append Mexico import/sale controls onto existing legal/tax packs."""
    specs = (
        (PRIVACY_LEGAL_PACK, "legal", "mx_nom_electrical_safety", "Mexico NOM-003-SCFI Electrical Safety",
         "Electrical products imported or sold in Mexico need NOM-003-SCFI-2014 safety evidence. Not legal advice.",
         ("nom-003", "lical"), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_nom_labeling", "Mexico NOM-024-SCFI Labeling",
         "Electronic/electrical products sold in Mexico need NOM-024-SCFI-2013 Spanish packaging, instructivo, and garantía evidence including the Mexican importer identity.",
         ("nom-024", "nom-024-platiica", "lfpc"), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_nom_electrical_installations", "Mexico NOM-001-SEDE Installations",
         "NOM-001-SEDE-2012 covers electrical installations (utilization). Default not_applicable for listed consumer plug-in families unless marked as installation equipment.",
         ("nom-001-sede",), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_lfpc_profeco", "Mexico LFPC / PROFECO",
         "Consumer-sale information, advertising, and safety duties under the Ley Federal de Protección al Consumidor. PROFECO enforces. Not legal advice.",
         ("lfpc", "lfpc-index"), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_infraestructura_calidad", "Mexico Ley de Infraestructura de la Calidad",
         "NOM conformity assessment is governed by the Ley de Infraestructura de la Calidad. Category membership is not a certificate.",
         ("lical",), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_telecom_homologation", "Mexico Telecom Homologation",
         "LMTR arts. 271-272: products that can connect to a telecom network or use radio spectrum must be homologated. Non-radio hydro is not_applicable. Dual-band/cellular hold. Official CoH only; supplier 'homologado' never satisfies launch.",
         ("lmtr", "lmtr-dof", "ehomologados", "crt", "ift-008", "ift-016", "ift-017"), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_nom_208_radio", "Mexico NOM-208 / IFT-008 Radio",
         "2.4 GHz / ISM spread-spectrum equipment is in the NOM-208-SCFI-2016 + IFT-008-2015 family when those bands are confirmed. Do not guess IFT-016/017/011.",
         ("nom-208", "ift-008"), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_ley_general_salud", "Mexico Ley General de Salud",
         "Sanitary-law overlay for inputs that may be health-regulated. Competence for a given nutrient/seed/pet-food SKU is unresolved without the exact product.",
         ("lgs", "cofepris"), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_cofepris_sector", "Mexico COFEPRIS Sector Permit",
         "COFEPRIS sanitary control is not inferred from the hydroponics or pet category. needs_evidence until an official authorization for the exact input exists.",
         ("cofepris", "lgs"), "public_beta_launch"),
        (PRIVACY_LEGAL_PACK, "legal", "mx_semarnat_sector", "Mexico SEMARNAT Sector Permit",
         "SEMARNAT environmental authorizations are not inferred from substrate/nutrient/electronics categories.",
         ("semarnat",), "public_beta_launch"),
        (TAX_PACK, "tax", "mx_importer_rfc", "Mexico Importer RFC",
         "Importer/seller RFC is required metadata for Mexico sale/import. Missing RFC is needs_evidence.",
         ("cff-sat-cfdi", "ladua"), "public_beta_launch"),
        (TAX_PACK, "tax", "mx_cfdi", "Mexico CFDI Invoicing",
         "CFDI 4.0 (CFF arts. 29 and 29-A; SAT Anexo 20) is required for Mexico invoicing. Missing CFDI is needs_evidence. Not a tax conclusion.",
         ("cff-sat-cfdi", "sat-anexo20"), "public_beta_launch"),
        (TAX_PACK, "tax", "mx_iva", "Mexico IVA",
         "Ley del IVA art. 1 taxes enajenación and importación in Mexico. SKU rate/exemption is accountant-reviewed evidence, never guessed.",
         ("liva",), "public_beta_launch"),
        (TAX_PACK, "tax", "mx_pedimento", "Mexico Pedimento / Aduanas",
         "Ley Aduanera despacho and pedimento evidence for imported goods. Domestic MX-origin goods may be not_applicable. Missing classification/pedimento is needs_evidence.",
         ("ladua", "snice"), "public_beta_launch"),
        (TAX_PACK, "tax", "mx_hs_classification", "Mexico HS / TIGIE Classification",
         "Unknown HS classification remains needs_evidence. Category is not a tariff code.",
         ("ladua", "snice"), "public_beta_launch"),
        (TAX_PACK, "tax", "mx_immex", "Mexico IMMEX If Claimed",
         "IMMEX is not required for ordinary importers. Applicable only when the packet claims IMMEX; otherwise not_applicable.",
         ("ladua",), "public_beta_launch"),
    )
    controls = []
    for pack_id, domain, key, name, description, source_ids, action in specs:
        controls.append(TrustControl(
            f"control-{pack_id}-{key}", name, domain, pack_id, f"{description} {LEGAL_DISCLAIMER}",
            (action,), ("management", "risk_approval", domain), ("mexico",), "high",
            (TrustEvidenceRequirement(f"{key}_evidence", f"Official Mexico evidence for {name}", True, 180, True),),
            "needs_professional_review", "lawyer/accountant review; never a software legal pass",
            _source_refs_for(*source_ids), 180, "risk_approval", True, "planned",
        ))
    return tuple(controls)


__all__ = [
    "PROMOTION_COMPLIANCE_GATE_ID", "ACCESS_DATE", "LEGAL_DISCLAIMER", "EVIDENCE_CLASSES",
    "REQUIREMENT_STATUSES", "REQUIREMENT_FAMILIES", "MARKETS", "PRODUCT_FAMILIES",
    "MexicoPolicySource", "MexicoProductCompliancePacket", "MexicoRequirementResult",
    "MexicoComplianceDecision", "mexico_policy_sources", "evaluate_mexico_product_compliance",
    "build_mexico_trust_controls", "citation_is_stale",
]
