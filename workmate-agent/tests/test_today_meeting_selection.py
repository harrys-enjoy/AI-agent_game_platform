import unittest


class TodayMeetingSelectionTests(unittest.TestCase):
    def test_selects_the_only_today_pending_meeting(self) -> None:
        from app.workflows.assistant_router import _select_today_pending_meeting_id

        meetings = [
            {
                "meeting_id": "m-today",
                "title": "회의 8월 22일 20:21",
                "created_at": "2026-08-22T11:22:33+00:00",
                "has_analysis": False,
            },
            {
                "meeting_id": "m-old",
                "title": "어제 회의",
                "created_at": "2026-08-21T11:22:33+00:00",
                "has_analysis": False,
            },
        ]

        self.assertEqual(
            _select_today_pending_meeting_id("오늘 회의 내용 분석해줘", meetings, "Asia/Seoul", today="2026-08-22"),
            "m-today",
        )

    def test_does_not_auto_select_when_today_has_multiple_pending_meetings(self) -> None:
        from app.workflows.assistant_router import _select_today_pending_meeting_id

        meetings = [
            {"meeting_id": "m-1", "title": "회의 1", "created_at": "2026-08-22T01:00:00+00:00", "has_analysis": False},
            {"meeting_id": "m-2", "title": "회의 2", "created_at": "2026-08-22T02:00:00+00:00", "has_analysis": False},
        ]

        self.assertIsNone(
            _select_today_pending_meeting_id("오늘 회의 분석해줘", meetings, "Asia/Seoul", today="2026-08-22")
        )


if __name__ == "__main__":
    unittest.main()
