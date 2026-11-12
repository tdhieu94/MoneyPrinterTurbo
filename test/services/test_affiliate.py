import unittest

from app.services import affiliate, llm


class TestAffiliateScriptTemplates(unittest.TestCase):
    def test_templates_fit_the_custom_requirements_limit(self):
        for template_id, prompt in affiliate.AFFILIATE_SCRIPT_TEMPLATES.items():
            with self.subTest(template_id=template_id):
                self.assertTrue(prompt.strip())
                self.assertLessEqual(len(prompt), llm.MAX_SCRIPT_PROMPT_LENGTH)
                self.assertEqual(
                    affiliate.get_affiliate_script_prompt(template_id), prompt
                )

    def test_none_and_unknown_templates_return_empty_text(self):
        self.assertEqual(affiliate.get_affiliate_script_prompt("none"), "")
        self.assertEqual(affiliate.get_affiliate_script_prompt(None), "")
        self.assertEqual(affiliate.get_affiliate_script_prompt("missing"), "")

    def test_template_ids_start_with_none(self):
        self.assertEqual(
            affiliate.AFFILIATE_TEMPLATE_IDS[0], affiliate.AFFILIATE_TEMPLATE_NONE
        )
        self.assertEqual(
            set(affiliate.AFFILIATE_TEMPLATE_IDS[1:]),
            set(affiliate.AFFILIATE_SCRIPT_TEMPLATES),
        )

    def test_template_reaches_the_script_prompt(self):
        requirements = affiliate.get_affiliate_script_prompt("quick_review")
        prompt = llm.build_script_prompt(
            video_subject="Máy xay mini cầm tay",
            language="vi-VN",
            video_script_prompt=requirements,
        )
        self.assertIn(requirements, prompt)


if __name__ == "__main__":
    unittest.main()
