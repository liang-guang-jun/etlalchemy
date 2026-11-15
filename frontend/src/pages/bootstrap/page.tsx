import { Link } from 'react-router';

import { BootstrapStatusCard } from '@/features/auth-bootstrap';
import { Button } from '@/shared/ui';

/**
 * Renders the bootstrap status page.
 *
 * @returns The bootstrap page content.
 */
export default function BootstrapPage() {
  return (
    <>
      <BootstrapStatusCard />
      <Link to="/login">
        <Button variant="secondary">Go to sign in</Button>
      </Link>
    </>
  );
}
