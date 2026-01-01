Feature: Router 能處理「口味+米種」句型
  Scenario: 「我要一個泡菜白米」至少要走飯糰域（不回 unknown）
    Given 系統已載入米種關鍵字
    When 使用者說「我要一個泡菜白米」
    Then Router 的 route_type 應為 "riceball"
    And needs_clarify 應為 false
