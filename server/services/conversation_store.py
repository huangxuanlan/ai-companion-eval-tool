"""
ConversationStore

仅供 ConversationService 内部使用的 conversation 域持久化薄封装。
不要在路由层或其他业务域直接 import 本模块作为公共基础设施。
"""
from __future__ import annotations

import database as db


class ConversationStore:
    def create_conversation(
        self,
        *,
        model_id: str,
        config: dict,
        preset_id: str | None = None,
        model_mini: str | None = None,
        prompt_version: str = "",
    ) -> str:
        return db.create_conversation(
            model_id=model_id,
            config=config,
            preset_id=preset_id,
            model_mini=model_mini,
            prompt_version=prompt_version,
        )

    def get_conversation(self, conv_id: str) -> dict | None:
        return db.get_conversation(conv_id)

    def list_conversations(self, **filters) -> list[dict]:
        return db.list_conversations(**filters)

    def update_conversation_status(self, conv_id: str, status: str) -> None:
        db.update_conversation_status(conv_id, status)

    def update_conversation_config(self, conv_id: str, config: dict) -> bool:
        return db.update_conversation_config(conv_id, config)

    def delete_conversation(self, conv_id: str) -> bool:
        return db.delete_conversation(conv_id)

    def set_conversation_pinned(self, conv_id: str, pinned: bool) -> bool:
        return db.set_conversation_pinned(conv_id, pinned)

    def set_conversation_archived(self, conv_id: str, archived: bool) -> bool:
        return db.set_conversation_archived(conv_id, archived)

    def delete_turn_results(self, conv_id: str) -> int:
        return db.delete_turn_results(conv_id)

    def delete_turn_result(self, conv_id: str, turn: int) -> int:
        return db.delete_turn_result(conv_id, turn)

    def insert_turn_result(self, conv_id: str, data: dict) -> int:
        return db.insert_turn_result(conv_id, data)

    def update_turn_dialogue_summary(
        self,
        conv_id: str,
        turn: int,
        dialogue_summary: str,
    ) -> bool:
        return db.update_turn_dialogue_summary(conv_id, turn, dialogue_summary)

    def update_turn_scores(self, conv_id: str, turn: int, scores: dict) -> None:
        db.update_turn_scores(conv_id, turn, scores)

    def infer_conversation_channel(
        self,
        config: dict | None,
        prompt_ref: str = "",
    ) -> str:
        return db.infer_conversation_channel(config, prompt_ref)

    def get_latest_conversation_channel(
        self,
        *,
        role_name: str = "",
        exclude_conv_id: str = "",
    ) -> str:
        return db.get_latest_conversation_channel(
            role_name=role_name,
            exclude_conv_id=exclude_conv_id,
        )

    def get_latest_dialogue_summary(
        self,
        *,
        role_name: str = "",
        exclude_conv_id: str = "",
    ) -> str:
        return db.get_latest_dialogue_summary(
            role_name=role_name,
            exclude_conv_id=exclude_conv_id,
        )
