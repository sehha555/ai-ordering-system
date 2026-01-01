Feature: riceball_tool fallback logic robustness
  As a system, I need to distinguish between real flavor hints and other keywords,
  so that I don't misinterpret user requests.

  Scenario: 單獨輸入米種不應解析成口味
    Given 系統已載入飯糰配方與米種關鍵字
    When 使用者說「紫米」
    Then parse_riceball_utterance 的 frame flavor 應為 None
    And missing_slots 應包含 "flavor"

  Scenario: 結帳不應被解析成飯糰口味
    Given 系統已載入飯糰配方
    When 使用者說「結帳」
    Then parse_riceball_utterance 的 frame flavor 應為 None

  Scenario: 「蛋餅」不應被解析成飯糰口味
    Given 系統已載入飯糰配方
    When 使用者說「蛋餅」
    Then parse_riceball_utterance 的 frame flavor 應為 None

  Scenario: 「我要一個泡菜白米」仍可解析出泡菜與白米
    Given 系統已載入飯糰配方與口味別名
    When 使用者說「我要一個泡菜白米」
    Then parse_riceball_utterance 應回傳 frame 且 flavor 為 "韓式泡菜"
    And frame 的 rice 為 "白米"

  Scenario: 「醬燒里肌」仍會要求米種
    Given 系統已載入飯糰配方
    When 使用者說「醬燒里肌」
    Then parse_riceball_utterance 應回傳 frame 且 flavor 為 "醬燒里肌"
    And missing_slots 應包含 "rice"
