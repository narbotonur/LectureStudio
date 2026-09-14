from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PyQt5.QtCore import QCoreApplication

from annie.gui.meeting_window import PrepGuideThread

from annie.study_guide import (
    StudySource,
    build_exam_guide_prompt,
    extract_study_source,
    generate_exam_prep_guide,
)


class StudyGuideExtractionTests(unittest.TestCase):
    def test_extracts_pptx_text_with_slide_labels(self):
        slide = b'''<?xml version="1.0" encoding="UTF-8"?>
        <p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>Induction</a:t></a:r>
        <a:r><a:t>Base case</a:t></a:r></a:p></p:sld>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'week1.pptx'
            with zipfile.ZipFile(path, 'w') as package:
                package.writestr('ppt/slides/slide1.xml', slide)
            source = extract_study_source(path)

        self.assertEqual(source.name, 'week1.pptx')
        self.assertIn('[Slide 1]', source.text)
        self.assertIn('InductionBase case', source.text)

    def test_extracts_docx_paragraphs(self):
        document = b'''<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Graph theory</w:t>
        </w:r></w:p><w:p><w:r><w:t>Euler path</w:t></w:r></w:p></w:body></w:document>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'notes.docx'
            with zipfile.ZipFile(path, 'w') as package:
                package.writestr('word/document.xml', document)
            source = extract_study_source(path)

        self.assertEqual(source.text, 'Graph theory\nEuler path')

    def test_image_uses_visual_analyzer(self):
        seen = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.jpef'
            path.write_bytes(b'\xff\xd8\xffimage')
            source = extract_study_source(
                path,
                visual_analyzer=lambda data, mime, name: seen.append((data, mime, name)) or 'formula',
            )

        self.assertEqual(source.text, 'formula')
        self.assertEqual(seen, [(b'\xff\xd8\xffimage', '', 'board.jpef')])


class StudyGuideGenerationTests(unittest.TestCase):
    def test_prompt_requires_source_labels_and_does_not_claim_exam_questions(self):
        prompt = build_exam_guide_prompt(
            [StudySource('lecture.pdf', '[Page 2]\nBayes theorem')],
            'midterm',
            'MATH 251',
        )
        self.assertIn('MATH 251 — Midterm Preparation Guide', prompt)
        self.assertIn('[Page 2]', prompt)
        self.assertIn('Do not claim these are real exam questions', prompt)
        self.assertIn('untrusted course material', prompt)

    @patch('annie.study_guide._generate_text', return_value='# Ready')
    @patch('annie.study_guide.extract_study_source')
    def test_multiple_files_generate_one_guide_and_report_skipped_files(self, extract, generate):
        extract.side_effect = [
            StudySource('slides.pptx', '[Slide 1]\nSets'),
            ValueError('damaged file'),
            StudySource('notes.docx', 'Functions'),
        ]
        messages = []
        guide = generate_exam_prep_guide(
            ['slides.pptx', 'broken.pdf', 'notes.docx'],
            'Final',
            'MATH 251',
            progress=messages.append,
        )

        self.assertIn('# Ready', guide)
        self.assertIn('broken.pdf: damaged file', guide)
        self.assertEqual(generate.call_count, 1)
        generated_prompt = generate.call_args.args[0]
        self.assertIn('slides.pptx', generated_prompt)
        self.assertIn('notes.docx', generated_prompt)
        self.assertTrue(any('Building final guide' in item for item in messages))

    @patch('annie.study_guide.generate_exam_prep_guide', return_value='# Delivered guide')
    def test_qt_worker_delivers_guide_to_ui_signal(self, generate):
        app = QCoreApplication.instance() or QCoreApplication([])
        received = []
        worker = PrepGuideThread(['slides.pdf'], 'Quiz', 'CSCI 231')
        worker.finished.connect(received.append)
        worker.start()
        self.assertTrue(worker.wait(3000))
        app.processEvents()

        self.assertEqual(received, ['# Delivered guide'])
        generate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
