import { Router, type IRouter } from "express";
import healthRouter from "./health";
import labRouter from "./lab";
import userDataRouter from "./userData";

const router: IRouter = Router();

router.use(healthRouter);
router.use(labRouter);
router.use(userDataRouter);

export default router;
