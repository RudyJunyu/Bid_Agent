from bid_agent.parsing.strategy import recommend_parse_method_from_profile


def test_native_complex_pdf_prefers_local_pdfplumber():
    method = recommend_parse_method_from_profile({
        'suffix': '.pdf',
        'pdf_type': 'native_text_pdf',
        'page_count': 94,
        'sample_pages': 5,
        'sample_text_chars': 6974,
        'text_layer_pages': 5,
        'empty_text_pages': 0,
    })
    assert method == 'pdfplumber'


def test_simple_text_pdf_uses_pdfplumber():
    method = recommend_parse_method_from_profile({
        'suffix': '.pdf',
        'pdf_type': 'simple_text_pdf',
        'page_count': 8,
        'sample_pages': 3,
        'sample_text_chars': 2400,
        'text_layer_pages': 3,
    })
    assert method == 'pdfplumber'


def test_mixed_pdf_with_usable_text_uses_pdfplumber():
    method = recommend_parse_method_from_profile({
        'suffix': '.pdf',
        'pdf_type': 'mixed_pdf',
        'page_count': 40,
        'sample_pages': 5,
        'sample_text_chars': 5000,
        'text_layer_pages': 5,
        'image_count': 12,
    })
    assert method == 'pdfplumber'


def test_scanned_pdf_still_recommends_mineru():
    method = recommend_parse_method_from_profile({
        'suffix': '.pdf',
        'pdf_type': 'scanned_pdf',
        'page_count': 60,
        'sample_pages': 5,
        'sample_text_chars': 0,
        'text_layer_pages': 0,
        'empty_text_pages': 5,
    })
    assert method == 'mineru_parallel_pages'


def test_scanned_short_pdf_uses_mineru_vlm():
    method = recommend_parse_method_from_profile({
        'suffix': '.pdf',
        'pdf_type': 'scanned_pdf',
        'page_count': 12,
        'sample_pages': 5,
        'sample_text_chars': 0,
        'text_layer_pages': 0,
        'empty_text_pages': 5,
    })
    assert method == 'mineru_vlm'
