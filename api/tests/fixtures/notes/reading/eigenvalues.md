# Власні значення та власні вектори

Синтетичний конспект для E2E-тестів; не є реальним підручником.

Число $\lambda$ є власним значенням квадратної матриці $A$, якщо існує ненульовий вектор $\mathbf{v}$ такий, що $A\mathbf{v} = \lambda\mathbf{v}$. Такий вектор називають власним вектором.

Рівність $A\mathbf{v} = \lambda\mathbf{v}$ рівносильна $(A - \lambda I)\mathbf{v} = \mathbf{0}$; ненульовий розв'язок існує тоді й лише тоді, коли $\det(A - \lambda I) = 0$. Це характеристичне рівняння.

Приклад: для матриці $A$ з рядками $(2, 1)$ та $(1, 2)$ характеристичне рівняння $(2 - \lambda)^2 - 1 = 0$ має корені $\lambda_1 = 3$ і $\lambda_2 = 1$; власний вектор для $\lambda_1$ дорівнює $(1, 1)^T$.

In English: an eigenvector keeps its direction under the linear map; only its length is scaled by the eigenvalue.
