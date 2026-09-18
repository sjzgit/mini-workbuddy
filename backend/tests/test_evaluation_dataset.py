"""评测数据集与导入导出测试（specs/012 US1，FR-001~003）。"""

import pytest

from app.services.evaluation import dataset_service


@pytest.fixture
def a_dataset(db_session):
    return dataset_service.create_dataset(db_session, "客服评测集", "基础评测")


class TestDatasetCrud:
    def test_create(self, db_session, a_dataset):
        assert a_dataset.name == "客服评测集"
        assert a_dataset.case_count == 0

    def test_list_and_get(self, db_session, a_dataset):
        items = dataset_service.list_datasets(db_session)
        assert [d.id for d in items] == [a_dataset.id]
        got = dataset_service.get_dataset(db_session, a_dataset.id)
        assert got.name == "客服评测集"

    def test_update(self, db_session, a_dataset):
        updated = dataset_service.update_dataset(
            db_session, a_dataset.id, "新名称", "新描述",
        )
        assert updated.name == "新名称"
        assert updated.description == "新描述"

    def test_delete(self, db_session, a_dataset):
        dataset_service.delete_dataset(db_session, a_dataset.id)
        with pytest.raises(dataset_service.DatasetNotFoundError):
            dataset_service.get_dataset(db_session, a_dataset.id)

    def test_create_blank_name_rejected(self, db_session):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            from app.schemas.evaluation import DatasetSaveRequest

            DatasetSaveRequest(name="  ", description="x")


class TestCaseCrud:
    def test_case_crud_roundtrip(self, db_session, a_dataset):
        case = dataset_service.create_case(
            db_session, a_dataset.id, "如何退款？", "答案A", "标准A",
        )
        assert case.dataset_id == a_dataset.id
        updated = dataset_service.update_case(
            db_session, a_dataset.id, case.id, "改后问题", None, None,
        )
        assert updated.expected_answer is None
        dataset_service.delete_case(db_session, a_dataset.id, case.id)
        assert dataset_service.list_cases(db_session, a_dataset.id) == []

    def test_case_dataset_must_exist(self, db_session, a_dataset):
        with pytest.raises(dataset_service.DatasetNotFoundError):
            dataset_service.create_case(db_session, 99999, "q", None, None)


class TestImportExport:
    VALID = {
        "name": "客服评测集",
        "description": "基础评测",
        "cases": [
            {"user_question": "q1", "expected_answer": "a1",
             "scoring_criteria": "c1"},
            {"user_question": "q2"},
        ],
    }

    def test_import_appends(self, db_session, a_dataset):
        result = dataset_service.import_cases(db_session, a_dataset.id, self.VALID)
        assert result.imported_cases == 2
        assert len(dataset_service.list_cases(db_session, a_dataset.id)) == 2

    def test_import_rejects_invalid(self, db_session, a_dataset):
        bad_cases = [
            {"cases": []},
            {"name": "x"},  # 缺 cases
            {"name": "x", "cases": [{"user_question": "  "}]},  # 空问题
            {"name": "x", "cases": [{"user_question": 123}]},  # 类型错
            {"name": "x", "cases": [{"user_question": "q", "expected_answer": 5}]},
            "not-a-dict",
        ]
        for payload in bad_cases:
            with pytest.raises(dataset_service.ImportValidationError) as exc:
                dataset_service.import_cases(db_session, a_dataset.id, payload)
            assert exc.value.errors
        # 整体拒绝：无部分导入
        assert dataset_service.list_cases(db_session, a_dataset.id) == []

    def test_export_roundtrip(self, db_session, a_dataset):
        dataset_service.import_cases(db_session, a_dataset.id, self.VALID)
        exported = dataset_service.export_dataset(db_session, a_dataset.id)
        assert exported["name"] == "客服评测集"
        assert len(exported["cases"]) == 2
        assert all("case_id" not in c for c in exported["cases"])
        # 可回导到新数据集
        fresh = dataset_service.create_dataset(db_session, "副本", "")
        result = dataset_service.import_cases(db_session, fresh.id, exported)
        assert result.imported_cases == 2
