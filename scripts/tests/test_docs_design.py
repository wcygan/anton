"""Exercise author mistakes and contrast regressions against the design guard."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('docs_design', ROOT / 'scripts/validate-docs-design.py')
design = importlib.util.module_from_spec(spec)
spec.loader.exec_module(design)


class DesignContractTests(unittest.TestCase):
    def test_current_site_passes(self):
        self.assertEqual(design.validate(ROOT), [])

    def test_mermaid_roles_and_references(self):
        valid = '```mermaid\nflowchart LR\n A["Client"]:::processing --> B[("Data")]:::storage\n```'
        self.assertEqual(design.source_errors(valid, 'example.md'), [])
        for invalid in (valid.replace(':::storage', ''), valid.replace(':::storage', ':::purple'), '```mermaid\nflowchart LR\n A --> B\n```'):
            self.assertTrue(design.source_errors(invalid, 'example.md'))

    def test_local_styling_and_raw_svg_are_rejected(self):
        for invalid in ('<svg />', '<div style={{color: "red"}} />', '```mermaid\nflowchart LR\n A[Box]:::flow\n style A fill:red\n```', '```mermaid\n%%{init: {"theme": "dark"}}%%\nflowchart LR\n A[Box]:::flow\n```'):
            self.assertTrue(design.source_errors(invalid, 'example.md'))

    def test_authoring_examples_are_not_rendered_shapes(self):
        self.assertEqual(design.source_errors('```tsx\n<svg />\n```', 'example.md'), [])

    def test_text_contrast_regression_fails(self):
        css = (ROOT / 'docs/src/css/tokens.css').read_text()
        self.assertTrue(design.palette_errors(css.replace('--diagram-node-text: #252525', '--diagram-node-text: #c4b5fd')))

    def test_shape_separation_regression_fails(self):
        css = (ROOT / 'docs/src/css/tokens.css').read_text()
        css = css.replace('--diagram-processing-fill: #c4b5fd', '--diagram-processing-fill: #252525').replace('--diagram-processing-stroke: #a78bfa', '--diagram-processing-stroke: #252525')
        self.assertTrue(any('shape must separate' in error for error in design.palette_errors(css)))

    def test_missing_palette_token_fails(self):
        css = (ROOT / 'docs/src/css/tokens.css').read_text()
        css = '\n'.join(line for line in css.splitlines() if '--diagram-storage-fill:' not in line)
        self.assertTrue(design.palette_errors(css))

    def test_named_css_color_bypass_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'docs/src/css'
            source.mkdir(parents=True)
            (source / 'Bad.css').write_text('.node {border: 1px solid red}')
            self.assertIn('CSS colors must reference tokens', '\n'.join(design.validate(root)))

    def test_component_color_bypass_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'docs/src/components'
            source.mkdir(parents=True)
            (source / 'Bad.tsx').write_text('export default () => <svg><rect fill="red" /></svg>')
            errors = '\n'.join(design.validate(root))
            self.assertIn('compose the shared Diagram primitives', errors)
            self.assertIn('use shared token classes', errors)


if __name__ == '__main__':
    unittest.main()
