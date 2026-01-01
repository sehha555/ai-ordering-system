Feature: 蛋白質歧義詞可引導補槽
  Scenario: 「醬燒里肌」應進入飯糰域並要求米種
    Given 系統已載入飯糰配方與口味提示
    When 使用者說「醬燒里肌」
    Then parse_riceball_utterance 應回傳 frame 且 flavor 為 "醬燒里肌"
    And frame 的 missing_slots 應包含 "rice"
    And 系統的澄清問句應詢問白米/紫米/混米
