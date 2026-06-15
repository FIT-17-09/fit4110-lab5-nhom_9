# Readiness Checklist (Lab 05)

- [x] DB đã khởi động và sẵn sàng (pg_isready check passed trong compose).
- [x] RabbitMQ đã chạy và có healthcheck trả về thành công (rabbitmq-diagnostics).
- [x] Worker (service AI/Background) đã tải và có health check trả 200 (sẵn sàng xử lý).
- [x] API đã kết nối được DB và queue (tạo message thành công và trả 201).
- [x] Các biến môi trường (`.env`) được đặt đúng, không dùng secret thật trực tiếp trong code.
- [x] `team-internal` network hoạt động; các service gọi nhau qua tên container (`db`, `rabbitmq`).
- [x] Version/tag của từng image được cập nhật theo đúng quy ước (v0.5.0).
