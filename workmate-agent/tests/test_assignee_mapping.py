import unittest


class AssigneeMappingTests(unittest.TestCase):
    def test_workmate_and_a2a_use_the_same_existing_user_id(self) -> None:
        from app.assignee_mapping import ASSIGNEE_TO_USER_ID

        self.assertEqual(ASSIGNEE_TO_USER_ID["변해훈"], "dev-assignee-gameqna")

    def test_existing_assignee_ids_are_not_renamed(self) -> None:
        from app.assignee_mapping import ASSIGNEE_TO_USER_ID

        self.assertEqual(
            ASSIGNEE_TO_USER_ID,
            {
                "서선정": "10464531542706509691",
                "배동우": "dev-assignee-video",
                "이승현": "dev-assignee-develop",
                "변해훈": "dev-assignee-gameqna",
            },
        )


if __name__ == "__main__":
    unittest.main()
