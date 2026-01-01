Feature: Router 能辨識飯糰常見錯字
  Scenario: 「飯團」應視為「飯糰」
    Given 系統已載入飯糰關鍵字
    When 使用者說「我要一個飯團」
    Then Router 的 route_type 應為 "riceball"
    And needs_clarify 應為 false
