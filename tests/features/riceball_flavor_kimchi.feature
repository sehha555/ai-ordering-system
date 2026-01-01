Feature: 泡菜應被視為飯糰口味
  Scenario: 「我要一個泡菜白米」應能直接解析出泡菜口味與白米
    Given 系統已載入飯糰配方與口味別名
    When 使用者說「我要一個泡菜白米」
    Then parse_riceball_utterance 應回傳 frame 且 flavor 為 "韓式泡菜"
    And frame 的 rice 為 "白米"
    And missing_slots 不應包含 "flavor"
