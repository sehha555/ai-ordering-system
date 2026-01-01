Feature: recipes fallback 不應短詞誤匹配長 key
  As a system, I need to ensure the recipe fallback logic is strict,
  so that short, non-flavor terms are not misinterpreted as longer recipe keys.

  Scenario: 短詞「蛋餅」不應命中較長的 recipe key（例如「蛋餅飯糰」）
    Given 系統已載入 riceball_recipes 的所有 keys
    And 系統存在包含 "蛋餅" 字樣的飯糰口味 key
    When 使用者說「蛋餅」
    Then parse_riceball_utterance 的 frame flavor 應為 None
    And frame 的 missing_slots 應包含 "flavor"

  Scenario: 僅當使用者輸入包含完整 recipe key 時才可命中 fallback
    Given 系統已載入 riceball_recipes 的所有 keys
    And recipes 中存在口味 key「醬燒里肌」
    When 使用者說「醬燒里肌」
    Then parse_riceball_utterance 應回傳 frame 且 flavor 為 "醬燒里肌"
    And frame 的 missing_slots 應包含 "rice"
