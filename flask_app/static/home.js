var typed = new Typed(".auto-type", {
    strings: [
      "Take Control",
      "Achieve Financial Freedom",
      "Master Your Money",
      "Secure Your Financial Future",
      "Budget Like a Pro",
    ],
    typeSpeed: 150,
    backSpeed: 150,
    loop: true,
  });
  
  // Add button click handlers
  document.querySelector('.learn-more').addEventListener('click', function() {
    window.location.href = 'login.html';
  });
  
  document.querySelector('.get-started').addEventListener('click', function() {
    window.location.href = 'login.html';
  });
  
  let li = document.querySelectorAll(".faq-text li");
  for (var i = 0; i < li.length; i++) {
    li[i].addEventListener("click", (e) => {
      let clickedLi;
      if (e.target.classList.contains("question-arrow")) {
        clickedLi = e.target.parentElement;
      } else {
        clickedLi = e.target.parentElement.parentElement;
      }
      clickedLi.classList.toggle("showAnswer");
    });
  }
  