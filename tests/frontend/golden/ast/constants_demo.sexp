(program
  (const int min_s 60)
  (const int hour_s (* 60 (identifier min_s)))
  (const int day_s (* 24 (identifier hour_s)))
  (def main
    (returns int)
    (block
      (expr (call println (+ "Seconds in a day: " (identifier day_s))))
      (return 0))))
