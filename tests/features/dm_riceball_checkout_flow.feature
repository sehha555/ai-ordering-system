Feature: 飯糰點餐與結帳閉環
  Background:
    Given 我有一個新的對話 session

  Scenario: 口味+米種一次到位可直接加入並結帳
    Given 我尚未加入任何品項
    When 我說「我要一個泡菜白米」
    Then 機器人應回覆「已加入」
    And 機器人回覆不應詢問米種或口味
    When 我說「結帳」
    Then 機器人應回覆「這樣一共」
    And 結帳金額應為泡菜飯糰的正確價格

  Scenario: 先講口味缺米，結帳會被攔截並引導補槽
    Given 我尚未加入任何品項
    When 我說「醬燒里肌」
    Then 機器人應詢問米種
    When 我說「結帳」
    Then 機器人應提醒尚缺米種
    When 我說「紫米」
    Then 機器人應回覆「已加入」
    When 我說「結帳」
    Then 機器人應回覆「這樣一共」
    And 結帳金額應為醬燒里肌紫米飯糰的正確價格
