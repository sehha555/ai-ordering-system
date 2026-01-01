Feature: Router 在飯糰補槽上下文可接住米種
  Background:
    Given current_order_has_main 為 true
  Scenario: 單獨輸入米種應路由到飯糰
    When 使用者說「紫米」
    Then Router 的 route_type 應為 "riceball"
    And note 應包含 "hit:rice_keyword_context"
