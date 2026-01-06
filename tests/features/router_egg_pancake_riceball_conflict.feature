Feature: Order Router Egg Pancake vs Riceball
  To ensure correct order routing, the system must prioritize "riceball" when keywords for both "egg pancake" and "riceball" are present.

  Scenario: User orders an "egg pancake riceball"
    Given Router 已載入各品類關鍵字與米種關鍵字
    When 使用者說「我要蛋餅飯糰」
    Then Router 的 route_type 應為 "riceball"
