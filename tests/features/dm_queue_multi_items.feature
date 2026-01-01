Feature: 單句多品項 queue 不被補槽打亂
  Background:
    Given 我有一個新的對話 session

  Scenario: 一句話點兩個飯糰，其中一個缺米能被逐一處理
    Given 我尚未加入任何品項
    When 我說「我要醬燒里肌跟泡菜白米」
    Then 機器人應詢問米種
    And 回應中不應包含「已加入」
    When 我說「白米」
    Then 機器人應回覆確認已加入醬燒里肌白米和泡菜白米
    And 機器人應詢問是否還需要什麼
