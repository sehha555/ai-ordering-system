Feature: 米種強訊號不應覆蓋明確非飯糰品類
  Scenario: 「我要單點薯餅紫米」應仍判定為 snack
    Given Router 已載入各品類關鍵字與米種關鍵字
    When 使用者說「我要單點薯餅紫米」
    Then Router 的 route_type 應為 "snack"
    And needs_clarify 應為 false
