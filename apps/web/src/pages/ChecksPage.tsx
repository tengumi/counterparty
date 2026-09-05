import { Button } from '@alfalab/core-components/button';
import { useNavigate } from 'react-router-dom';
import styles from '../App.module.css';

export function ChecksPage() {
  const navigate = useNavigate();

  return (
    <section className={styles.content}>
      <h1>Проверка контрагентов</h1>
      <p className={styles.subtitle}>Разберитесь, готовы ли вы работать с компанией и на каких условиях</p>
      <div className={styles.card}>
        <h2>Мои проверки</h2>
        <p>Здесь появятся ваши проверки и разговоры с помощником.</p>
        <p className={styles.muted}>Демонстрационный экран. Создание проверок пока недоступно.</p>
        <Button view="primary" size={40} onClick={() => navigate('/checks/demo-project/chats/demo-thread')}>
          Открыть пример проверки
        </Button>
      </div>
    </section>
  );
}
